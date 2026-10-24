import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ConfigError, load_settings  # noqa: E402

GOOD = {"AGENT_SEED_PHRASE": "a-long-private-seed-phrase-for-tests"}


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        s = load_settings(GOOD)
        self.assertEqual(s.agent_name, "agri-swarm-agent")
        self.assertEqual(s.agent_port, 8000)
        self.assertTrue(s.agent_mailbox)
        self.assertEqual(s.max_drones, 200)

    def test_missing_seed_fails_clearly(self):
        with self.assertRaises(ConfigError) as cm:
            load_settings({})
        self.assertIn("AGENT_SEED_PHRASE", str(cm.exception))

    def test_short_seed_rejected(self):
        with self.assertRaises(ConfigError):
            load_settings({"AGENT_SEED_PHRASE": "short"})

    def test_bad_numbers_rejected(self):
        for key, val in [("AGENT_PORT", "abc"), ("MAX_DRONES", "0"), ("MAX_DRONES", "9999"),
                         ("RUN_TIME_BUDGET_SECONDS", "x"), ("LOG_LEVEL", "LOUD"),
                         ("AGENT_MAILBOX", "maybe")]:
            with self.subTest(key=key, val=val):
                with self.assertRaises(ConfigError):
                    load_settings({**GOOD, key: val})

    def test_overrides(self):
        s = load_settings({**GOOD, "MAX_DRONES": "50", "AGENT_MAILBOX": "false", "LOG_LEVEL": "debug"})
        self.assertEqual((s.max_drones, s.agent_mailbox, s.log_level), (50, False, "DEBUG"))

    def test_seed_not_in_repr_or_error(self):
        s = load_settings(GOOD)
        self.assertNotIn(GOOD["AGENT_SEED_PHRASE"], repr(s))
        with self.assertRaises(ConfigError) as cm:
            load_settings({**GOOD, "MAX_DRONES": "bad"})
        self.assertNotIn(GOOD["AGENT_SEED_PHRASE"], str(cm.exception))


if __name__ == "__main__":
    unittest.main()
