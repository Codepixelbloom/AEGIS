"""Agri-Swarm agent: uAgents entry point (setup, handlers, orchestration only).

Two interfaces share the same service layer:
  * Chat protocol (ASI:One / Agentverse chat): plain-text commands -> text replies.
  * AgriSwarmControl protocol: typed SwarmRequest -> SwarmResponse for other agents.

Business logic lives in services/; handlers only validate, delegate, and reply.
"""
import asyncio
import logging
import sys
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)

from config import ConfigError, Settings, load_settings
from models import PROTOCOL_NAME, PROTOCOL_VERSION, SwarmRequest, SwarmResponse
from services.memory import SessionStore
from services.swarm_engine import Swarm
from services.tools import Command, ToolLimits, execute, handle_chat_text

logger = logging.getLogger("agri-swarm")

SAFE_ERROR_TEXT = "Sorry - something went wrong while handling that request. Please try again."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text_message(text: str) -> ChatMessage:
    return ChatMessage(timestamp=_now(), msg_id=uuid4(), content=[TextContent(type="text", text=text)])


def build_agent(settings: Settings) -> Agent:
    """Create the agent, its session store and both protocols."""
    limits = ToolLimits(
        max_drones=settings.max_drones,
        max_ticks_per_request=settings.max_ticks_per_request,
        run_time_budget_seconds=settings.run_time_budget_seconds,
        max_message_chars=settings.max_message_chars,
    )
    store = SessionStore(
        max_sessions=settings.max_sessions,
        ttl_seconds=settings.session_ttl_seconds,
        factory=lambda: Swarm(max_drones=settings.max_drones),
    )

    agent = Agent(
        name=settings.agent_name,
        seed=settings.agent_seed_phrase,
        port=settings.agent_port,
        mailbox=settings.agent_mailbox,
        readme_path="README.md",
        publish_agent_details=True,
    )

    # ---- Chat protocol (ASI:One-compatible) -------------------------------------------
    chat_proto = Protocol(spec=chat_protocol_spec)

    @chat_proto.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
        # Acknowledge first, as the chat protocol expects.
        await ctx.send(sender, ChatAcknowledgement(timestamp=_now(), acknowledged_msg_id=msg.msg_id))
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
        try:
            # The simulation is synchronous CPU work: keep it off the event loop.
            reply = await asyncio.to_thread(handle_chat_text, store, sender, text, limits)
        except Exception:  # never crash the agent; log type/traceback, not user text
            ctx.logger.exception("chat request failed")
            reply = SAFE_ERROR_TEXT
        await ctx.send(sender, _text_message(reply))

    @chat_proto.on_message(ChatAcknowledgement)
    async def on_chat_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        ctx.logger.debug("ack received for %s", msg.acknowledged_msg_id)

    # ---- Typed protocol for other agents ----------------------------------------------
    control = Protocol(name=PROTOCOL_NAME, version=PROTOCOL_VERSION)

    @control.on_message(model=SwarmRequest, replies=SwarmResponse)
    async def on_request(ctx: Context, sender: str, req: SwarmRequest) -> None:
        cmd = Command(action=req.action, count=req.count, drone_id=req.drone_id, ticks=req.ticks)
        if cmd.action in ("add", "reset") and cmd.count > limits.max_drones:
            await ctx.send(sender, SwarmResponse(ok=False, message="Rejected.",
                                                 error=f"count exceeds {limits.max_drones}"))
            return
        if cmd.action in ("step", "run") and cmd.ticks > limits.max_ticks_per_request:
            await ctx.send(sender, SwarmResponse(ok=False, message="Rejected.",
                                                 error=f"ticks exceeds {limits.max_ticks_per_request}"))
            return
        if cmd.action in ("remove", "fail") and cmd.drone_id is None:
            await ctx.send(sender, SwarmResponse(ok=False, message="Rejected.", error="drone_id is required"))
            return
        try:
            result = await asyncio.to_thread(execute, store, sender, cmd, limits)
        except Exception:
            ctx.logger.exception("typed request failed")
            await ctx.send(sender, SwarmResponse(ok=False, message="Failed.", error="internal error"))
            return
        snap = result.snapshot or {}
        await ctx.send(sender, SwarmResponse(
            ok=result.ok, message=result.message, error=result.error, map_text=result.map_text,
            tick=snap.get("tick", 0), drones=snap.get("drones", 0),
            zones_done=snap.get("zones_done", 0), zones_total=snap.get("zones_total", 0),
            stressed_cells_treated=snap.get("stressed_cells_treated", 0),
            stressed_cells_total=snap.get("stressed_cells_total", 0),
            mission_complete=snap.get("mission_complete", False),
        ))

    agent.include(chat_proto, publish_manifest=True)
    agent.include(control, publish_manifest=True)

    @agent.on_event("startup")
    async def on_startup(ctx: Context) -> None:
        ctx.logger.info("Agri-Swarm agent started; address=%s", agent.address)

    return agent


def _load() -> Settings:
    try:
        return load_settings()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)


settings = _load()
logging.basicConfig(level=getattr(logging, settings.log_level))
agent = build_agent(settings)

if __name__ == "__main__":
    agent.run()
