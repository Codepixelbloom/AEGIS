"""Minimal stand-ins for uagents / uagents_core so wiring tests run without the real SDK.

Only installed when the real packages are missing. They mimic just the surface agent.py uses;
they do NOT prove compatibility with the real SDK - run the agent for real to verify that.
"""
import sys
import types


def install_if_missing() -> bool:
    """Install stubs if `uagents` can't be imported. Returns True if stubs were installed."""
    try:
        import uagents  # noqa: F401
        import uagents_core.contrib.protocols.chat  # noqa: F401
        return False
    except ImportError:
        pass

    class Model:
        def __init__(self, **kw):
            for name, default in getattr(type(self), "__defaults__map__", {}).items():
                setattr(self, name, default)
            for k, v in kw.items():
                setattr(self, k, v)

        def __init_subclass__(cls, **kw):
            defaults = {}
            for base in reversed(cls.__mro__):
                for name in getattr(base, "__annotations__", {}):
                    if hasattr(base, name):
                        val = getattr(base, name)
                        defaults[name] = val.default if isinstance(val, _FieldInfo) else val
            cls.__defaults__map__ = defaults

    class _FieldInfo:
        def __init__(self, default=None, **kw):
            self.default = default

    def Field(default=None, **kw):
        return _FieldInfo(default)

    class Context:
        def __init__(self):
            self.sent = []
            self.logger = types.SimpleNamespace(
                info=lambda *a, **k: None, debug=lambda *a, **k: None,
                exception=lambda *a, **k: None, warning=lambda *a, **k: None)

        async def send(self, dest, msg):
            self.sent.append((dest, msg))

    class Protocol:
        def __init__(self, name=None, version=None, spec=None):
            self.name, self.version, self.spec = name, version, spec
            self.handlers = {}

        def on_message(self, model, replies=None):
            def deco(fn):
                self.handlers[model] = fn
                return fn
            return deco

    class Agent:
        def __init__(self, **kw):
            self.kw = kw
            self.protocols = []
            self.address = "agent1qstub"

        def include(self, proto, publish_manifest=False):
            self.protocols.append((proto, publish_manifest))

        def on_event(self, name):
            return lambda fn: fn

        def run(self):
            pass

    uagents = types.ModuleType("uagents")
    uagents.Agent, uagents.Context, uagents.Protocol = Agent, Context, Protocol
    uagents.Model, uagents.Field = Model, Field

    chat = types.ModuleType("uagents_core.contrib.protocols.chat")

    class TextContent(Model):
        pass

    class ChatMessage(Model):
        pass

    class ChatAcknowledgement(Model):
        pass

    chat.TextContent, chat.ChatMessage, chat.ChatAcknowledgement = TextContent, ChatMessage, ChatAcknowledgement
    chat.chat_protocol_spec = object()

    for name, mod in (("uagents", uagents), ("uagents_core", types.ModuleType("uagents_core")),
                      ("uagents_core.contrib", types.ModuleType("uagents_core.contrib")),
                      ("uagents_core.contrib.protocols", types.ModuleType("uagents_core.contrib.protocols")),
                      ("uagents_core.contrib.protocols.chat", chat)):
        sys.modules[name] = mod
    return True
