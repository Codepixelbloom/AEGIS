"""Tool layer: parse requests, run swarm actions, and format results.

Everything here is deterministic ordinary Python (no LLM, no network). Inputs are validated
and every action is bounded (drone cap, tick cap, wall-clock budget) so one request cannot
hang or exhaust the agent.
"""
import re
import time
from dataclasses import dataclass
from typing import Optional

from .memory import SessionStore

ACTIONS = ("status", "add", "remove", "fail", "step", "run", "reset", "map")

HELP_TEXT = (
    "Agri-Swarm: a decentralized drone swarm that scouts a field and spot-treats stressed crop. "
    "There is no master drone - drones bid for zones themselves.\n\n"
    "Commands:\n"
    "- add [N]      launch N drones at the base (default 1)\n"
    "- remove ID    retire a drone; its zones are re-auctioned\n"
    "- fail ID      simulate a crash; its zones are re-auctioned\n"
    "- run [N]      run the mission (up to N ticks)\n"
    "- step [N]     advance N ticks (default 1)\n"
    "- status       mission progress and drone table\n"
    "- map          draw the field\n"
    "- reset [N]    restart the same field with N drones (default 3)"
)


class CommandError(ValueError):
    """A request that cannot be understood or is out of bounds. Message is safe to show users."""


@dataclass(frozen=True)
class ToolLimits:
    max_drones: int = 200
    max_ticks_per_request: int = 500
    run_time_budget_seconds: float = 5.0
    max_message_chars: int = 500


@dataclass(frozen=True)
class Command:
    action: str
    count: int = 1
    drone_id: Optional[int] = None
    ticks: int = 1


@dataclass
class Result:
    ok: bool
    message: str
    error: Optional[str] = None
    snapshot: Optional[dict] = None
    map_text: Optional[str] = None


# --------------------------------------------------------------------------- parsing
_VERBS = {
    "add": "add", "launch": "add", "deploy": "add", "spawn": "add",
    "remove": "remove", "retire": "remove", "recall": "remove",
    "fail": "fail", "crash": "fail", "kill": "fail",
    "step": "step", "tick": "step",
    "run": "run", "go": "run", "start": "run", "continue": "run",
    "status": "status", "progress": "status", "state": "status",
    "map": "map", "field": "map",
    "reset": "reset", "restart": "reset", "new": "reset",
}


def parse_command(text: str, limits: ToolLimits = ToolLimits()) -> Optional[Command]:
    """Turn chat text into a Command. Returns None for help/empty input.

    Raises CommandError for oversized or out-of-range requests.
    """
    if text is None:
        return None
    if len(text) > limits.max_message_chars:
        raise CommandError(f"Message too long (limit {limits.max_message_chars} characters).")
    words = re.findall(r"[a-z]+|\d+", text.lower())
    if not words or words[0] in ("help", "hi", "hello", "hey"):
        return None
    if "help" in words:
        return None

    verb = next((w for w in words if w in _VERBS), None)
    if verb is None:
        return None
    action = _VERBS[verb]
    numbers = [int(w) for w in words if w.isdigit()]
    if any(n > 10**9 for n in numbers):
        raise CommandError("Number out of range.")
    first = numbers[0] if numbers else None

    if action == "add":
        count = 1 if first is None else first
        if not 1 <= count <= limits.max_drones:
            raise CommandError(f"Drone count must be between 1 and {limits.max_drones}.")
        return Command("add", count=count)
    if action in ("remove", "fail"):
        if first is None or first < 1:
            raise CommandError(f"Which drone? Example: '{action} 3'.")
        return Command(action, drone_id=first)
    if action == "step":
        ticks = 1 if first is None else first
        if not 1 <= ticks <= limits.max_ticks_per_request:
            raise CommandError(f"Ticks must be between 1 and {limits.max_ticks_per_request}.")
        return Command("step", ticks=ticks)
    if action == "run":
        ticks = limits.max_ticks_per_request if first is None else first
        if not 1 <= ticks <= limits.max_ticks_per_request:
            raise CommandError(f"Ticks must be between 1 and {limits.max_ticks_per_request}.")
        return Command("run", ticks=ticks)
    if action == "reset":
        count = 3 if first is None else first
        if not 1 <= count <= limits.max_drones:
            raise CommandError(f"Drone count must be between 1 and {limits.max_drones}.")
        return Command("reset", count=count)
    return Command(action)


# --------------------------------------------------------------------------- execution
def _summary(snap: dict) -> str:
    done = " - MISSION COMPLETE" if snap["mission_complete"] else ""
    return (f"Tick {snap['tick']} | {snap['drones']} drones | zones {snap['zones_done']}/"
            f"{snap['zones_total']} | stressed cells treated "
            f"{snap['stressed_cells_treated']}/{snap['stressed_cells_total']}{done}")


def _drone_table(swarm, max_rows: int = 15) -> str:
    drones = sorted(swarm.alive(), key=lambda d: d.id)
    rows = ["id | state | battery | zones done"]
    for d in drones[:max_rows]:
        rows.append(f"{d.id} | {d.state} | {d.battery:.0f}% | {d.zones_done}")
    if len(drones) > max_rows:
        rows.append(f"... and {len(drones) - max_rows} more drones")
    return "\n".join(rows)


def _run(swarm, ticks: int, budget_seconds: float) -> str:
    start, ran = time.monotonic(), 0
    while ran < ticks and not swarm.finished and swarm.alive():
        chunk = min(5, ticks - ran)
        swarm.step(chunk)
        ran += chunk
        if time.monotonic() - start > budget_seconds:
            return f"Ran {ran} ticks (time budget reached; send 'run' to continue)."
    if swarm.finished:
        return f"Ran {ran} ticks - the whole field has been scouted and treated."
    if not swarm.alive():
        return f"Ran {ran} ticks - no drones left; use 'add' to launch more."
    return f"Ran {ran} ticks (send 'run' to continue)."


def execute(store: SessionStore, session_key: str, cmd: Command,
            limits: ToolLimits = ToolLimits()) -> Result:
    """Run one command against the sender's swarm session."""
    session = store.get(session_key)
    with session.lock:
        swarm = session.swarm
        swarm.max_drones = limits.max_drones
        action = cmd.action

        if action == "add":
            ids = swarm.add_drones(cmd.count)
            if not ids:
                return _result(swarm, False, error=f"Drone cap reached ({limits.max_drones}).")
            note = f"Launched {len(ids)} drone(s): ids {ids[0]}-{ids[-1]}."
            if len(ids) < cmd.count:
                note += f" (Capped at {limits.max_drones} drones.)"
            return _result(swarm, True, note)
        if action in ("remove", "fail"):
            if not swarm.remove_drone(cmd.drone_id, crashed=(action == "fail")):
                return _result(swarm, False, error=f"No active drone with id {cmd.drone_id}.")
            verb = "crashed" if action == "fail" else "retired"
            return _result(swarm, True, f"Drone {cmd.drone_id} {verb}; its zones go back to the auction.")
        if action == "step":
            swarm.step(cmd.ticks)
            return _result(swarm, True, f"Advanced {cmd.ticks} tick(s).")
        if action == "run":
            return _result(swarm, True, _run(swarm, cmd.ticks, limits.run_time_budget_seconds))
        if action == "reset":
            swarm.reset(cmd.count)
            return _result(swarm, True, f"Field reset with {cmd.count} drone(s).")
        if action == "map":
            return _result(swarm, True, "Field map:", with_map=True)
        if action == "status":
            return _result(swarm, True, _drone_table(swarm))
        return _result(swarm, False, error=f"Unknown action {action!r}.")


def _result(swarm, ok: bool, message: str = "", error: Optional[str] = None,
            with_map: bool = False) -> Result:
    snap = swarm.snapshot()
    if not ok:
        return Result(False, error or "Request failed.", error=error, snapshot=snap)
    return Result(True, f"{message}\n{_summary(snap)}", snapshot=snap,
                  map_text=swarm.render() if with_map else None)


# --------------------------------------------------------------------------- chat entry
def handle_chat_text(store: SessionStore, session_key: str, text: str,
                     limits: ToolLimits = ToolLimits()) -> str:
    """Full text-in/text-out path used by the ASI:One chat handler."""
    try:
        cmd = parse_command(text, limits)
    except CommandError as exc:
        return f"{exc}\n\n{HELP_TEXT}"
    if cmd is None:
        return HELP_TEXT
    result = execute(store, session_key, cmd, limits)
    return format_chat(result)


def format_chat(result: Result) -> str:
    if not result.ok:
        return f"Sorry - {result.error}"
    if result.map_text:
        return f"{result.message}\n\n```\n{result.map_text}\n```"
    return result.message
