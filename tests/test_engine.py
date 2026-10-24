import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.swarm_engine import Swarm  # noqa: E402


def run_to_end(swarm, limit=3000):
    while not swarm.finished and swarm.tick < limit and swarm.alive():
        swarm.step(5)


class EngineTests(unittest.TestCase):
    def test_mission_completes_for_various_fleet_sizes(self):
        for n in (1, 3, 10, 40):
            with self.subTest(drones=n):
                s = Swarm(n_drones=n)
                run_to_end(s)
                snap = s.snapshot()
                self.assertTrue(snap["mission_complete"])
                self.assertEqual(snap["stressed_cells_treated"], snap["stressed_cells_total"])

    def test_more_drones_finish_faster(self):
        slow, fast = Swarm(n_drones=1), Swarm(n_drones=10)
        run_to_end(slow)
        run_to_end(fast)
        self.assertLess(fast.tick, slow.tick)

    def test_add_drones_mid_mission(self):
        s = Swarm(n_drones=2)
        s.step(20)
        before = len(s.alive())
        ids = s.add_drones(5)
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(s.alive()), before + 5)
        run_to_end(s)
        self.assertTrue(s.finished)

    def test_drone_cap_enforced(self):
        s = Swarm(n_drones=10, max_drones=4)
        self.assertEqual(len(s.alive()), 4)
        self.assertEqual(s.add_drones(3), [])

    def test_crash_zones_are_reassigned(self):
        s = Swarm(n_drones=4)
        s.step(15)
        victim = next(d for d in s.alive() if d.current)
        self.assertTrue(s.remove_drone(victim.id, crashed=True))
        run_to_end(s)
        self.assertTrue(s.finished)

    def test_remove_unknown_drone(self):
        self.assertFalse(Swarm(n_drones=1).remove_drone(999))

    def test_no_zone_worked_by_two_drones(self):
        s = Swarm(n_drones=15)
        for _ in range(60):
            s.step(1)
            locks = [d.current.id for d in s.alive() if d.current]
            self.assertEqual(len(locks), len(set(locks)))

    def test_deterministic_for_same_seed(self):
        a, b = Swarm(n_drones=5), Swarm(n_drones=5)
        a.step(50)
        b.step(50)
        self.assertEqual(a.snapshot(), b.snapshot())

    def test_battery_never_negative(self):
        s = Swarm(n_drones=3)
        for _ in range(300):
            s.step(1)
            self.assertTrue(all(d.battery > 0 for d in s.alive()))


if __name__ == "__main__":
    unittest.main()
