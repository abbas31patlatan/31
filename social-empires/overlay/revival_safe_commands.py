"""Conservative, server-authoritative subset of Social Empires game commands.

Unsupported/unsafe commands are rejected atomically. This is intentionally NOT
a complete Social Empires implementation: rewards, combat, timers, gifts,
client-supplied XP, cash offers, quest completion and map expansion still need
protocol research and server-side rules before they can be enabled.

Only use with single-process upstream save storage.
"""
import copy
import json
import math
import os
import re
import tempfile
import threading
from pathlib import Path

_COMMAND_LOCK = threading.RLock()
_PACKET = re.compile(r"^[a-fA-F0-9]{64};", re.ASCII)
_ALLOWED = frozenset({"game_status", "name_map", "move", "orient", "buy", "sell"})
_RESOURCE_KEYS = {"w": "wood", "s": "stone", "f": "food", "g": "coins", "c": "cash"}


class PacketRejected(ValueError):
    pass


def _integer(value, name, minimum=0, maximum=100000000):
    if isinstance(value, bool) or isinstance(value, (list, dict)) or not isinstance(value, (str, int, float)):
        raise PacketRejected(f"Invalid {name}")
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        raise PacketRejected(f"Invalid {name}")
    if isinstance(value, str) and (not value.isascii() or not re.fullmatch(r"[0-9]{1,9}", value)):
        raise PacketRejected(f"Invalid {name}")
    try:
        parsed = int(value)
    except (ValueError, OverflowError):
        raise PacketRejected(f"Invalid {name}")
    if parsed < minimum or parsed > maximum:
        raise PacketRejected(f"{name} out of range")
    return parsed


def _map(save, town):
    index = _integer(town, "town", maximum=len(save["maps"])-1)
    return save["maps"][index], index


def _existing_item(game_map, item_id, x, y):
    for item in game_map["items"]:
        if item[0] == item_id and item[1] == x and item[2] == y:
            return item
    raise PacketRejected("Item does not exist at location")


def _position(args, start=0):
    return (
        _integer(args[start], "x", maximum=127),
        _integer(args[start+1], "y", maximum=127),
    )


def _item_definition(item_id, item_lookup):
    item = item_lookup(item_id)
    if not isinstance(item, dict) or not item.get("cost_type") in _RESOURCE_KEYS:
        raise PacketRejected("Unknown/unsupported item")
    cost = _integer(item.get("cost"), "server item cost", minimum=1)
    return item, cost


def _apply_buy(save, args, item_lookup, now):
    if len(args) != 8:
        raise PacketRejected("Invalid buy arguments")
    item_id = _integer(args[0], "item", maximum=1000000)
    x, y = _position(args, 1)
    game_map, _ = _map(save, args[4])
    # The upstream client uses optional free or discounted spawn flags. A
    # public server must NOT trust them to authorize unearned items.
    free = _integer(args[5], "free buy flag", maximum=1)
    multiplier = args[6]
    if free != 0 or type(multiplier) not in (int, float) or multiplier != 1:
        raise PacketRejected("Client discounts/free spawns are not trusted")
    item, cost = _item_definition(item_id, item_lookup)
    resource = _RESOURCE_KEYS[item["cost_type"]]
    wallet = save["playerInfo"] if resource == "cash" else game_map
    if wallet.get(resource, 0) < cost:
        raise PacketRejected("Insufficient resources")
    if any(obj[1] == x and obj[2] == y for obj in game_map["items"]):
        raise PacketRejected("Occupied coordinate")
    wallet[resource] -= cost
    game_map["xp"] += _integer(item.get("xp") or 0, "item xp", maximum=100000)
    game_map["items"].append([item_id, x, y, 0, now, 0])


def _apply_sell(save, args, item_lookup):
    if len(args) != 6:
        raise PacketRejected("Invalid sell arguments")
    x, y = _position(args)
    item_id = _integer(args[2], "item", maximum=1000000)
    game_map, _ = _map(save, args[3])
    # Do not trust a client flag or 'KILL' to avoid payment rules.
    if args[4] not in (0, False) or args[5] not in ("MouseUsed", "sell", "Sell", ""):
        raise PacketRejected("Unverified sale mode")
    _item_definition(item_id, item_lookup)
    game_map["items"].remove(_existing_item(game_map, item_id, x, y))
    # No refund until sale prices and discounts are known and verified.


def _apply_move(save, args):
    if len(args) != 8:
        raise PacketRejected("Invalid move arguments")
    old_x, old_y = _position(args)
    item_id = _integer(args[2], "item", maximum=1000000)
    new_x, new_y = _position(args, 3)
    game_map, _ = _map(save, args[6])
    item = _existing_item(game_map, item_id, old_x, old_y)
    if any(other is not item and other[1] == new_x and other[2] == new_y for other in game_map["items"]):
        raise PacketRejected("Occupied target")
    item[1], item[2] = new_x, new_y


def _apply_orient(save, args):
    if len(args) != 4:
        raise PacketRejected("Invalid orientation arguments")
    x, y = _position(args)
    facing = _integer(args[2], "orientation", maximum=7)
    game_map, _ = _map(save, args[3])
    for item in game_map["items"]:
        if item[1] == x and item[2] == y:
            item[3] = facing
            return
    raise PacketRejected("Item does not exist")


def _apply_command(save, cmd, args, item_lookup, now):
    if cmd not in _ALLOWED or not isinstance(args, list):
        raise PacketRejected("Command not supported")
    if cmd == "game_status":
        if len(args) > 12:
            raise PacketRejected("Invalid game status")
    elif cmd == "name_map":
        if len(args) != 2 or not isinstance(args[1], str) or not 1 <= len(args[1]) <= 32:
            raise PacketRejected("Invalid map name")
        _, index = _map(save, args[0])
        if not args[1].isprintable() or "<" in args[1] or ">" in args[1]:
            raise PacketRejected("Invalid map name characters")
        save["playerInfo"]["map_names"][index] = args[1]
    elif cmd == "move":
        _apply_move(save, args)
    elif cmd == "orient":
        _apply_orient(save, args)
    elif cmd == "buy":
        _apply_buy(save, args, item_lookup, now)
    elif cmd == "sell":
        _apply_sell(save, args, item_lookup)


def parse_packet(raw):
    if not isinstance(raw, str) or len(raw) > 65536 or not _PACKET.match(raw):
        raise PacketRejected("Malformed command envelope")
    try:
        document = json.loads(raw[65:])
    except (TypeError, json.JSONDecodeError):
        raise PacketRejected("Invalid command JSON")
    if not isinstance(document, dict) or not isinstance(document.get("commands"), list):
        raise PacketRejected("Missing commands")
    commands = document["commands"]
    if len(commands) > 32 or not commands:
        raise PacketRejected("Invalid batch size")
    for item in commands:
        if not isinstance(item, dict) or not isinstance(item.get("cmd"), str) or not isinstance(item.get("args"), list):
            raise PacketRejected("Invalid command entry")
    # The 64-character legacy prefix is *not* a MAC and is not trusted.
    return commands


def apply_batch(original, raw_packet, item_lookup, now):
    """Return validated new state; no mutation on failed batches."""
    commands = parse_packet(raw_packet)
    draft = copy.deepcopy(original)
    for command in commands:
        _apply_command(draft, command["cmd"], command["args"], item_lookup, now)
    return draft


def _durable_write(village_id, draft, saves_dir):
    root = Path(saves_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r"[a-f0-9-]{36}", village_id):
        raise PacketRejected("Invalid village ID")
    destination = root / (village_id + ".save.json")
    fd, tmp = tempfile.mkstemp(prefix=".revival-", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(draft, stream, indent=4)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def execute(village_id, raw, get_session, item_lookup, saves_dir, clock):
    with _COMMAND_LOCK:
        original = get_session(village_id)
        if original is None:
            raise PacketRejected("Village missing")
        draft = apply_batch(original, raw, item_lookup, int(clock()))
        _durable_write(village_id, draft, saves_dir)
        original.clear()
        original.update(draft)
        return {"result": "success"}
