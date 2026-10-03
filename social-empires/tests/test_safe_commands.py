"""Server-side command invariants; no SWF binary or public network needed."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "revival_safe_commands", ROOT / "overlay" / "revival_safe_commands.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def packet(*commands):
    return ("a" * 64) + ";" + json.dumps({"commands": [
        {"cmd": cmd, "args": args} for cmd, args in commands
    ]})


def game():
    return {
        "playerInfo": {"cash": 20, "map_names": ["My Empire"]},
        "maps": [{"coins": 250, "wood": 100, "stone": 20, "food": 100,
                  "xp": 0, "items": [[26, 50, 50, 0, 0, 0]]}],
        "privateState": {"completedMissions": [], "rewardedMissions": []},
    }


def lookup(item_id):
    if item_id == 1:
        return {"cost": "40", "cost_type": "w", "xp": "5"}
    if item_id == 2:
        return {"cost": "10", "cost_type": "c", "xp": "2"}
    if item_id == 19:
        return {"cost": "0", "cost_type": "g", "collect": "20",
                "collect_type": "w", "collect_xp": "1"}
    return None


class GameCommandsTests(unittest.TestCase):
    def test_purchase_deducts_server_price_and_can_move(self):
        original = game()
        changed = mod.apply_batch(
            original, packet(
                ("buy", [1, 55, 50, 0, 0, 0, 1, 0]),
                ("move", [55, 50, 1, 56, 50, 0, 0, "MouseUsed"]),
                ("orient", [56, 50, 3, 0]),
                ("name_map", [0, "Village One"]),
            ), lookup, 1234)
        self.assertEqual(original["maps"][0]["wood"], 100)
        self.assertEqual(changed["maps"][0]["wood"], 60)
        self.assertEqual(changed["maps"][0]["xp"], 5)
        self.assertEqual(changed["playerInfo"]["map_names"][0], "Village One")
        self.assertIn([1, 56, 50, 3, 1234, 0], changed["maps"][0]["items"])

    def test_cash_purchase_uses_private_wallet(self):
        changed = mod.apply_batch(game(), packet(("buy", [2, 49, 49, 0, 0, 0, 1, 0])), lookup, 123)
        self.assertEqual(changed["playerInfo"]["cash"], 10)

    def test_rejects_client_cheats(self):
        bad = [
            ("buy", [1, 60, 50, 0, 0, 1, 1, 0]),   # free buy
            ("buy", [1, 60, 50, 0, 0, 0, 0.1, 0]), # discount
            ("buy", [1, 60, 50, 0, 0, 0, -1, 0]),  # resource exploit
            ("buy", [1, 60, 50, 0, 999, 0, 1, 0]),# invalid map
            ("buy", [1, 50, 50, 0, 0, 0, 1, 0]),  # occupied
            ("buy", [1, -1, 60, 0, 0, 0, 1, 0]),
            ("buy", [9999, 49, 49, 0, 0, 0, 1, 0]),
            ("move", [12, 12, 1, 60, 60, 0, 0, "MouseUsed"]),
            ("orient", [50, 50, 999, 0]),
            ("sell", [12, 12, 1, 0, 0, "sell"]),
            ("win_bonus", [100000000, 0, 0, 0, 0]),
            ("reward_mission", [0, 1]),
            ("collect_new", [50, 50, 0, 1, 0, 999999, 0]),
            ("attack_player", ["another-player", 100]),
            ("name_map", [0, "<script>"]),
        ]
        state = game()
        snapshot = copy.deepcopy(state)
        for name, args in bad:
            with self.subTest(command=name, args=args):
                with self.assertRaises(mod.PacketRejected):
                    mod.apply_batch(state, packet((name, args)), lookup, 1)
                self.assertEqual(state, snapshot)

    def test_whole_batch_rolls_back_if_last_command_is_bad(self):
        original = game()
        with self.assertRaises(mod.PacketRejected):
            mod.apply_batch(original, packet(
                ("buy", [1, 52, 52, 0, 0, 0, 1, 0]),
                ("win_bonus", [9999999, 0, 0, 0, 0]),
            ), lookup, 1)
        self.assertEqual(original, game())

    def test_harvesting_requires_owned_entity_and_server_cooldown(self):
        original = game()
        original["maps"][0]["items"].append([19, 52, 52, 0, 0, 0])
        harvest = packet(("collect_new", [52, 52, 0, 19, 0, 1, 0]))
        first = mod.apply_batch(original, harvest, lookup, 1000)
        self.assertEqual(first["maps"][0]["wood"], 120)
        self.assertEqual(first["maps"][0]["xp"], 1)
        self.assertEqual(original["maps"][0]["wood"], 100)
        for bad in (
            packet(("collect_new", [52, 52, 0, 19, 0, 99999, 0])),
            packet(("collect_new", [55, 55, 0, 19, 0, 1, 0])),
        ):
            with self.assertRaises(mod.PacketRejected):
                mod.apply_batch(first, bad, lookup, 2000)
        with self.assertRaises(mod.PacketRejected):
            mod.apply_batch(first, harvest, lookup, 1010)
        second = mod.apply_batch(first, harvest, lookup, 1300)
        self.assertEqual(second["maps"][0]["wood"], 140)

    def test_bounded_packets_and_malformed_values(self):
        for value in ("no packet", "a"*64+";[]", "a"*64+";{}", "x"*64+";{}",
                      "a"*64+";not json", packet(*[("game_status", [])]*33)):
            with self.subTest(value=value[:15]):
                with self.assertRaises(mod.PacketRejected):
                    mod.parse_packet(value)

    def test_sale_checks_ownership_and_never_mints_refunds(self):
        source = game()
        source["maps"][0]["items"].append([1, 60, 60, 0, 0, 0])
        result = mod.apply_batch(source, packet(("sell", [60, 60, 1, 0, 0, "sell"])), lookup, 1234)
        self.assertEqual(len(result["maps"][0]["items"]), 1)
        self.assertEqual(result["maps"][0]["wood"], source["maps"][0]["wood"])


if __name__ == "__main__":
    unittest.main()
