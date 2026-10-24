"""Handler wiring tests. Uses stand-in uagents modules when the real SDK isn't installed."""
import asyncio
import importlib
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import _stubs  # noqa: E402

USING_STUBS = _stubs.install_if_missing()

ENV = {"AGENT_SEED_PHRASE": "a-long-private-seed-phrase-for-tests", "AGENT_MAILBOX": "false"}


def load_agent_module():
    with mock.patch.dict(os.environ, ENV, clear=False):
        for name in ("config", "models", "agent"):
            sys.modules.pop(name, None)
        return importlib.import_module("agent")


class AgentWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_agent_module()
        from uagents import Context
        from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent
        cls.Context, cls.Ack, cls.Msg, cls.Text = Context, ChatAcknowledgement, ChatMessage, TextContent

    def _protocols(self):
        return {p.name or "chat": p for p, _ in self.mod.agent.protocols}

    def test_protocols_included_with_manifest(self):
        if not USING_STUBS:
            self.skipTest("real SDK: inspect agent.protocols differently")
        self.assertEqual(len(self.mod.agent.protocols), 2)
        self.assertTrue(all(pub for _, pub in self.mod.agent.protocols))

    def test_chat_handler_acks_then_replies(self):
        if not USING_STUBS:
            self.skipTest("handler registry only inspectable on stubs")
        chat = next(p for p, _ in self.mod.agent.protocols if p.spec is not None)
        handler = chat.handlers[self.Msg]
        ctx = self.Context()
        msg = self.Msg(msg_id="m1", timestamp=None, content=[self.Text(type="text", text="add 4 drones")])
        asyncio.run(handler(ctx, "agent1qsender", msg))
        self.assertEqual(len(ctx.sent), 2)
        self.assertIsInstance(ctx.sent[0][1], self.Ack)
        self.assertEqual(ctx.sent[0][1].acknowledged_msg_id, "m1")
        reply_text = ctx.sent[1][1].content[0].text
        self.assertIn("Launched 4 drone(s)", reply_text)

    def test_chat_handler_survives_internal_failure(self):
        if not USING_STUBS:
            self.skipTest("handler registry only inspectable on stubs")
        chat = next(p for p, _ in self.mod.agent.protocols if p.spec is not None)
        handler = chat.handlers[self.Msg]
        ctx = self.Context()
        msg = self.Msg(msg_id="m2", timestamp=None, content=[self.Text(type="text", text="status")])
        with mock.patch.object(self.mod, "handle_chat_text", side_effect=RuntimeError("boom secret-token")):
            asyncio.run(handler(ctx, "agent1qsender", msg))
        reply_text = ctx.sent[-1][1].content[0].text
        self.assertEqual(reply_text, self.mod.SAFE_ERROR_TEXT)
        self.assertNotIn("secret-token", reply_text)

    def test_typed_request_returns_structured_response(self):
        if not USING_STUBS:
            self.skipTest("handler registry only inspectable on stubs")
        from models import SwarmRequest, SwarmResponse
        ctrl = next(p for p, _ in self.mod.agent.protocols if p.spec is None)
        handler = ctrl.handlers[SwarmRequest]
        ctx = self.Context()
        asyncio.run(handler(ctx, "agent1qother", SwarmRequest(action="add", count=5, drone_id=None, ticks=1)))
        resp = ctx.sent[0][1]
        self.assertIsInstance(resp, SwarmResponse)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.drones, 8)

    def test_typed_request_rejects_out_of_bounds(self):
        if not USING_STUBS:
            self.skipTest("handler registry only inspectable on stubs")
        from models import SwarmRequest
        ctrl = next(p for p, _ in self.mod.agent.protocols if p.spec is None)
        handler = ctrl.handlers[SwarmRequest]
        ctx = self.Context()
        asyncio.run(handler(ctx, "agent1qother", SwarmRequest(action="add", count=9999, drone_id=None, ticks=1)))
        self.assertFalse(ctx.sent[0][1].ok)
        ctx2 = self.Context()
        asyncio.run(handler(ctx2, "agent1qother", SwarmRequest(action="remove", count=1, drone_id=None, ticks=1)))
        self.assertFalse(ctx2.sent[0][1].ok)


class MissingConfigTests(unittest.TestCase):
    def test_import_without_seed_exits_with_clear_message(self):
        env = {k: v for k, v in os.environ.items() if k != "AGENT_SEED_PHRASE"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("config._load_dotenv", lambda: None):
            for name in ("config", "models", "agent"):
                sys.modules.pop(name, None)
            with self.assertRaises(SystemExit) as cm:
                importlib.import_module("agent")
        self.assertEqual(cm.exception.code, 2)
        for name in ("config", "models", "agent"):
            sys.modules.pop(name, None)


if __name__ == "__main__":
    unittest.main()
