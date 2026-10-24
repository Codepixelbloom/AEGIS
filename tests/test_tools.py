import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.memory import SessionStore  # noqa: E402
from services.swarm_engine import Swarm  # noqa: E402
from services.tools import (CommandError, Command, ToolLimits, execute,  # noqa: E402
                            handle_chat_text, parse_command)

LIMITS = ToolLimits(max_drones=50, max_ticks_per_request=200, run_time_budget_seconds=5, max_message_chars=100)


class ParseTests(unittest.TestCase):
    def test_valid_commands(self):
        cases = {
            "add 5 drones": Command("add", count=5),
            "Please launch 12 drones to the field": Command("add", count=12),
            "add": Command("add", count=1),
            "remove drone 3": Command("remove", drone_id=3),
            "fail 7": Command("fail", drone_id=7),
            "step 10": Command("step", ticks=10),
            "run": Command("run", ticks=200),
            "run 50": Command("run", ticks=50),
            "status": Command("status"),
            "show status": Command("status"),
            "show map": Command("map"),
            "reset 4": Command("reset", count=4),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_command(text, LIMITS), expected)

    def test_help_and_unknown_return_none(self):
        for text in ("", "help", "hello", "what is the weather", "   "):
            with self.subTest(text=text):
                self.assertIsNone(parse_command(text, LIMITS))

    def test_out_of_range_rejected(self):
        for text in ("add 51", "add 0", "step 201", "run 0", "remove", "fail 0", "add 99999999999"):
            with self.subTest(text=text):
                with self.assertRaises(CommandError):
                    parse_command(text, LIMITS)

    def test_oversized_message_rejected(self):
        with self.assertRaises(CommandError):
            parse_command("add " + "x" * 200, LIMITS)


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.store = SessionStore(factory=lambda: Swarm(max_drones=50))

    def test_response_structure(self):
        r = execute(self.store, "u", Command("add", count=3), LIMITS)
        self.assertTrue(r.ok)
        for key in ("tick", "drones", "zones_done", "zones_total", "stressed_cells_treated",
                    "stressed_cells_total", "mission_complete"):
            self.assertIn(key, r.snapshot)
        self.assertEqual(r.snapshot["drones"], 6)

    def test_run_completes_mission(self):
        execute(self.store, "u", Command("add", count=10), LIMITS)
        r = execute(self.store, "u", Command("run", ticks=200), LIMITS)
        self.assertTrue(r.snapshot["mission_complete"])
        self.assertIn("MISSION COMPLETE", r.message)

    def test_run_respects_tick_bound(self):
        r = execute(self.store, "u", Command("run", ticks=5), LIMITS)
        self.assertLessEqual(r.snapshot["tick"], 5)

    def test_run_respects_time_budget(self):
        tight = ToolLimits(max_drones=50, max_ticks_per_request=200, run_time_budget_seconds=0.0)
        r = execute(self.store, "u", Command("run", ticks=200), tight)
        self.assertIn("time budget", r.message)
        self.assertLess(r.snapshot["tick"], 200)

    def test_unknown_drone_is_safe_error(self):
        r = execute(self.store, "u", Command("remove", drone_id=999), LIMITS)
        self.assertFalse(r.ok)
        self.assertIn("999", r.error)

    def test_sessions_are_isolated(self):
        execute(self.store, "alice", Command("add", count=10), LIMITS)
        r = execute(self.store, "bob", Command("status"), LIMITS)
        self.assertEqual(r.snapshot["drones"], 3)

    def test_map_returns_text(self):
        r = execute(self.store, "u", Command("map"), LIMITS)
        self.assertIn("unscanned", r.map_text)


class ChatTextTests(unittest.TestCase):
    def setUp(self):
        self.store = SessionStore(factory=lambda: Swarm(max_drones=50))

    def test_help_on_unknown(self):
        self.assertIn("Commands:", handle_chat_text(self.store, "u", "dance", LIMITS))

    def test_bad_input_returns_error_plus_help(self):
        out = handle_chat_text(self.store, "u", "add 9999", LIMITS)
        self.assertIn("between 1 and 50", out)
        self.assertIn("Commands:", out)

    def test_map_is_code_block(self):
        self.assertIn("```", handle_chat_text(self.store, "u", "map", LIMITS))

    def test_add_then_status_flow(self):
        handle_chat_text(self.store, "u", "add 5 drones", LIMITS)
        out = handle_chat_text(self.store, "u", "status", LIMITS)
        self.assertIn("8 drones", out)


class StoreTests(unittest.TestCase):
    def test_lru_eviction(self):
        store = SessionStore(max_sessions=2)
        store.get("a"); store.get("b"); store.get("c")
        self.assertEqual(len(store), 2)

    def test_ttl_expiry(self):
        now = [0.0]
        store = SessionStore(ttl_seconds=60, clock=lambda: now[0])
        first = store.get("a")
        now[0] = 61.0
        self.assertIsNot(store.get("a"), first)


if __name__ == "__main__":
    unittest.main()
