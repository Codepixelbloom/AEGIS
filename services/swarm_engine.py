"""Swarm engine: decentralized agricultural drone swarm simulation.

Pure Python, no network, no uAgents imports - so it is deterministic and unit-testable.
Drones scout a field zone by zone and spot-treat stressed crop. Work is divided with a
CBBA-style auction (bundle building + highest-bid conflict resolution); there is no
master drone. Drones can be added, removed or failed at any time.
"""
import math
import random
from dataclasses import dataclass
from typing import List, Optional

# ----------------------------------------------------------------- parameters
ZONE = 5                 # zone size in cells (one zone = one task)
STRESS_THRESHOLD = 0.35  # cell needs treatment above this stress level
BATTERY_MAX = 100.0
MOVE_COST = 0.3          # battery per cell travelled
WORK_COST = 0.2          # battery per tick of scanning/spraying
CHARGE_RATE = 5.0        # battery per tick at base
RESERVE = 8.0            # battery that must remain when landing
MAX_BUNDLE = 3           # tasks a drone queues ahead (CBBA bundle size)


# ----------------------------------------------------------------- data types
@dataclass
class Task:
    id: int
    cx: float
    cy: float
    cells: list
    needy: int
    work: float                      # ticks of work to scan + treat the zone
    progress: float = 0.0
    done: bool = False
    locked_by: Optional[int] = None  # drone currently working on it

    @property
    def remaining(self) -> float:
        return max(0.0, self.work - self.progress)


class Drone:
    def __init__(self, drone_id: int, x: float, y: float):
        self.id = drone_id
        self.x, self.y = x, y
        self.battery = BATTERY_MAX
        self.state = "idle"          # idle|moving|working|returning|charging|failed
        self.current: Optional[Task] = None
        self.bundle: List[Task] = []
        self.zones_done = 0
        self.alive = True

    def dist(self, x: float, y: float) -> float:
        return math.hypot(self.x - x, self.y - y)


# ----------------------------------------------------------------- simulation
class Swarm:
    def __init__(self, width: int = 40, height: int = 30, seed: int = 7,
                 n_drones: int = 3, max_drones: int = 200):
        self.width, self.height, self.seed = width, height, seed
        self.max_drones = max_drones
        self.base = (0.0, 0.0)
        self.reset(n_drones)

    # -- setup ---------------------------------------------------------------
    def reset(self, n_drones: int = 0) -> None:
        rng = random.Random(self.seed)
        self.rng = random.Random(self.seed + 1)      # spawn jitter; keeps runs reproducible
        w, h = self.width, self.height
        self.stress = [[0.0] * w for _ in range(h)]
        for _ in range(max(4, (w * h) // 200)):          # random infested patches
            cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(2, 5)
            for y in range(h):
                for x in range(w):
                    d = math.hypot(x - cx, y - cy)
                    if d < r:
                        self.stress[y][x] = max(self.stress[y][x], 1 - d / r)

        self.tasks: List[Task] = []
        for zy in range(0, h, ZONE):
            for zx in range(0, w, ZONE):
                cells = [(x, y) for y in range(zy, min(zy + ZONE, h))
                         for x in range(zx, min(zx + ZONE, w))]
                needy = sum(self.stress[y][x] > STRESS_THRESHOLD for x, y in cells)
                self.tasks.append(Task(
                    id=len(self.tasks),
                    cx=sum(c[0] for c in cells) / len(cells),
                    cy=sum(c[1] for c in cells) / len(cells),
                    cells=cells, needy=needy,
                    work=4 + 0.5 * needy))

        self.drones: List[Drone] = []
        self.next_id = 1
        self.tick = 0
        self.dirty = True
        self.add_drones(n_drones)

    # -- drone management ----------------------------------------------------
    def add_drones(self, n: int = 1) -> List[int]:
        """Add up to n drones at the base; returns the new ids (fewer if the cap is hit)."""
        ids: List[int] = []
        for _ in range(n):
            if len(self.alive()) >= self.max_drones:
                break
            d = Drone(self.next_id, self.base[0] + self.rng.uniform(0, 1.5),
                      self.base[1] + self.rng.uniform(0, 1.5))
            self.next_id += 1
            self.drones.append(d)
            ids.append(d.id)
        self.dirty = True
        return ids

    def get(self, drone_id: int) -> Optional[Drone]:
        return next((d for d in self.drones if d.id == drone_id and d.alive), None)

    def remove_drone(self, drone_id: int, crashed=False) -> bool:
        d = self.get(drone_id)
        if not d:
            return False
        self._release(d)
        d.alive, d.state = False, "failed"
        if not crashed:
            self.drones.remove(d)
        self.dirty = True
        return True

    def alive(self) -> List[Drone]:
        return [d for d in self.drones if d.alive]

    def _release(self, d: Drone):
        if d.current:
            d.current.locked_by = None   # progress is kept; another drone resumes it
            d.current = None
        d.bundle = []

    # -- CBBA-style allocation -----------------------------------------------
    def _route(self, d: Drone, bundle: List[Task]):
        """Energy needed to finish current task + bundle; returns (energy, end position)."""
        pos, energy = (d.x, d.y), 0.0
        if d.current:
            energy += d.current.remaining * WORK_COST
            pos = (d.current.cx, d.current.cy)
        for t in bundle:
            energy += math.hypot(pos[0] - t.cx, pos[1] - t.cy) * MOVE_COST + t.remaining * WORK_COST
            pos = (t.cx, t.cy)
        return energy, pos

    def _feasible(self, d: Drone, bundle: List[Task]) -> bool:
        energy, pos = self._route(d, bundle)
        back = math.hypot(pos[0] - self.base[0], pos[1] - self.base[1]) * MOVE_COST
        return d.battery - energy - back >= RESERVE

    @staticmethod
    def _bid(pos, t: Task) -> float:
        # closer + more infested zones score higher
        return (1 + 0.1 * t.needy) / (1 + math.hypot(pos[0] - t.cx, pos[1] - t.cy) / ZONE)

    def allocate(self):
        """Bundle building + max-bid conflict resolution, repeated until stable.

        Each round every drone bids on its single best remaining zone (given where
        its bundle would leave it). If several drones want the same zone, the
        highest bid wins (ties -> lower id); losers simply re-bid next round.
        """
        taken = set()
        team = [d for d in self.alive() if d.state not in ("returning", "charging")]
        for d in team:
            d.bundle = []
        free = [t for t in self.tasks if not t.done and t.locked_by is None]
        while True:
            claims = {}                                  # task id -> (bid, -drone id, drone, task)
            for d in team:
                if len(d.bundle) >= MAX_BUNDLE:
                    continue
                pos = (d.bundle[-1].cx, d.bundle[-1].cy) if d.bundle else \
                      ((d.current.cx, d.current.cy) if d.current else (d.x, d.y))
                best = None
                for t in free:
                    if t.id in taken or not self._feasible(d, d.bundle + [t]):
                        continue
                    b = self._bid(pos, t)
                    if best is None or b > best[0]:
                        best = (b, t)
                if best:
                    cand = (best[0], -d.id, d, best[1])
                    cur = claims.get(best[1].id)
                    if cur is None or cand[:2] > cur[:2]:
                        claims[best[1].id] = cand
            if not claims:
                break
            for tid, (_, _, d, t) in claims.items():
                d.bundle.append(t)
                taken.add(tid)
        self.dirty = False

    # -- per-tick behaviour --------------------------------------------------
    def _move_towards(self, d: Drone, x, y) -> bool:
        dist = d.dist(x, y)
        if dist <= 1.0:
            d.battery -= dist * MOVE_COST
            d.x, d.y = x, y
            return True
        d.x += (x - d.x) / dist
        d.y += (y - d.y) / dist
        d.battery -= MOVE_COST
        return False

    def _step_drone(self, d: Drone):
        at_base = d.dist(*self.base) < 1.5
        if d.state == "charging" or (at_base and d.battery < BATTERY_MAX - 1 and not d.current):
            d.state = "charging"
            d.battery = min(BATTERY_MAX, d.battery + CHARGE_RATE)
            if d.battery >= BATTERY_MAX - 1:
                d.state = "idle"
                self.dirty = True
            return
        if d.state == "returning":
            if self._move_towards(d, *self.base):
                d.state = "charging"
            return

        # low battery -> abort, hand work back to the swarm, fly home
        if d.battery < d.dist(*self.base) * MOVE_COST + RESERVE and not (d.current and at_base):
            self._release(d)
            d.state = "returning"
            self.dirty = True
            return

        if d.current is None and d.bundle:
            t = d.bundle[0]
            if self._move_towards(d, t.cx, t.cy):
                if t.locked_by in (None, d.id) and not t.done:
                    d.bundle.pop(0)
                    d.current, t.locked_by = t, d.id
                else:                               # someone else got there first
                    d.bundle.pop(0)
                    self.dirty = True
            else:
                d.state = "moving"
            return

        if d.current:
            t = d.current
            d.state = "working"
            t.progress += 1
            d.battery -= WORK_COST
            if t.progress >= t.work:
                t.done, t.locked_by = True, None
                d.current = None
                d.zones_done += 1
                self.dirty = True
            return

        d.state = "idle"
        if d.dist(*self.base) > 1.5:                 # nothing to do: go home and recharge
            d.state = "returning"

    def step(self, n=1):
        for _ in range(n):
            self.tick += 1
            if self.dirty or self.tick % 10 == 0:
                self.allocate()
            for d in self.alive():
                self._step_drone(d)

    # -- reporting -----------------------------------------------------------
    @property
    def finished(self) -> bool:
        return all(t.done for t in self.tasks)

    def summary(self) -> str:
        done = sum(t.done for t in self.tasks)
        treated = sum(t.needy for t in self.tasks if t.done)
        total = sum(t.needy for t in self.tasks)
        return (f"tick {self.tick} | drones {len(self.alive())} | zones {done}/{len(self.tasks)} "
                f"| stressed cells treated {treated}/{total}")

    def status(self) -> str:
        rows = ["  id  state      battery  pos          current  queue  zones"]
        for d in self.drones:
            cur = d.current.id if d.current else "-"
            q = ",".join(str(t.id) for t in d.bundle) or "-"
            rows.append(f"  {d.id:<3} {d.state:<10} {d.battery:6.1f}  "
                        f"({d.x:5.1f},{d.y:5.1f})  {cur!s:<7}  {q:<5}  {d.zones_done}")
        return "\n".join(rows)

    def snapshot(self) -> dict:
        """Plain-data view of mission progress (used by the agent's typed responses)."""
        return {
            "tick": self.tick,
            "drones": len(self.alive()),
            "zones_done": sum(t.done for t in self.tasks),
            "zones_total": len(self.tasks),
            "stressed_cells_treated": sum(t.needy for t in self.tasks if t.done),
            "stressed_cells_total": sum(t.needy for t in self.tasks),
            "mission_complete": self.finished,
        }

    def render(self) -> str:
        zones_w = math.ceil(self.width / ZONE)
        grid = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                t = self.tasks[(y // ZONE) * zones_w + (x // ZONE)]
                if not t.done:
                    row.append(".")
                else:
                    row.append("+" if self.stress[y][x] > STRESS_THRESHOLD else "-")
            grid.append(row)
        for d in self.alive():
            gx, gy = min(self.width - 1, int(d.x)), min(self.height - 1, int(d.y))
            grid[gy][gx] = str(d.id % 10)
        grid[0][0] = grid[0][0] if grid[0][0].isdigit() else "B"
        legend = ".=unscanned  -=scanned healthy  +=treated  digits=drones (id%10)  B=base"
        return "\n".join("".join(r) for r in reversed(grid)) + "\n" + legend
