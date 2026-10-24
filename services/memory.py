"""Session store: one swarm simulation per conversation partner (sender address).

Persistence policy: IN-MEMORY ONLY. Sessions are lost when the agent restarts and are not
shared between replicas. Data kept: simulation state only (no message text, no personal data).
Retention: idle sessions expire after `ttl_seconds`; at most `max_sessions` are kept
(least recently used is evicted first).
"""
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional

from .swarm_engine import Swarm


class Session:
    def __init__(self, swarm: Swarm):
        self.swarm = swarm
        self.lock = threading.Lock()      # serialises concurrent requests from one sender
        self.last_used = time.monotonic()


class SessionStore:
    def __init__(self, max_sessions: int = 100, ttl_seconds: int = 3600,
                 factory: Optional[Callable[[], Swarm]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self._max = max_sessions
        self._ttl = ttl_seconds
        self._factory = factory or Swarm
        self._clock = clock
        self._sessions: "OrderedDict[str, Session]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Session:
        """Return the sender's session, creating it (and pruning old ones) if needed."""
        now = self._clock()
        with self._lock:
            for k in [k for k, s in self._sessions.items() if now - s.last_used > self._ttl]:
                del self._sessions[k]
            session = self._sessions.get(key)
            if session is None:
                session = Session(self._factory())
                self._sessions[key] = session
                while len(self._sessions) > self._max:
                    self._sessions.popitem(last=False)
            session.last_used = now
            self._sessions.move_to_end(key)
            return session

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
