"""Typed message schemas for agent-to-agent requests (the chat protocol covers ASI:One).

Keep these stable: changing a field is a protocol change. Bump PROTOCOL_VERSION deliberately.
"""
from typing import Literal, Optional

from uagents import Field, Model

PROTOCOL_NAME = "AgriSwarmControl"
PROTOCOL_VERSION = "0.1.0"

Action = Literal["status", "add", "remove", "fail", "step", "run", "reset", "map"]


class SwarmRequest(Model):
    """Control request for one swarm session (a session is keyed by the sender's address)."""
    action: Action
    count: int = Field(default=1, ge=1, le=500, description="Drones to add (action=add) or drones after reset")
    drone_id: Optional[int] = Field(default=None, ge=1, description="Target drone (remove/fail)")
    ticks: int = Field(default=1, ge=1, le=5000, description="Ticks to advance (action=step)")


class SwarmResponse(Model):
    """Structured response. When ok is False, `error` explains why and the rest is best-effort."""
    ok: bool
    message: str
    error: Optional[str] = None
    tick: int = 0
    drones: int = 0
    zones_done: int = 0
    zones_total: int = 0
    stressed_cells_treated: int = 0
    stressed_cells_total: int = 0
    mission_complete: bool = False
    map_text: Optional[str] = None
