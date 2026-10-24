# AEGIS

A decentralized agricultural drone-swarm simulator exposed as a [uAgents](https://uagents.fetch.ai)
agent for Agentverse and ASI:One chat. Chat with it to launch drones, add more at any time,
crash or retire drones, and watch the swarm scout a field and spot-treat stressed crop
(weeds / pests / water stress).

There is **no master drone**: each drone bids for field zones using only its own position and
battery (a CBBA-style auction with highest-bid conflict resolution). If a drone fails, its
zones are re-auctioned and another drone resumes the partial work. This is a **simulation** -
no real aircraft are controlled.

## Chat commands

| Command | Effect |
| --- | --- |
| `add [N]` | Launch N drones at the base (default 1) |
| `remove ID` | Retire a drone; its zones are re-auctioned |
| `fail ID` | Simulate a crash; its zones are re-auctioned |
| `run [N]` | Run up to N ticks (bounded by `MAX_TICKS_PER_REQUEST` and a time budget) |
| `step [N]` | Advance N ticks |
| `status` | Mission progress and drone table |
| `map` | Draw the field (`.` unscanned, `-` scanned healthy, `+` treated, digits = drones) |
| `reset [N]` | Restart the same field with N drones (default 3) |
| `help` | Show this list |

Each sender address gets its own swarm session.

## Typed protocol (agent-to-agent)

`AgriSwarmControl` v0.1.0: send `SwarmRequest(action, count, drone_id, ticks)`, receive
`SwarmResponse(ok, message, error, tick, drones, zones_done, zones_total,
stressed_cells_treated, stressed_cells_total, mission_complete, map_text)`. See `models.py`.

## Project layout

```
agri-swarm-agent/
├── agent.py             # uAgent setup, chat + typed handlers (thin)
├── models.py            # SwarmRequest / SwarmResponse schemas
├── config.py            # validated env settings, fails early
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── services/
│   ├── swarm_engine.py  # simulation + CBBA-style allocation (pure Python)
│   ├── tools.py         # command parsing, bounded execution, formatting
│   └── memory.py        # in-memory per-sender sessions (TTL + LRU)
└── tests/               # unittest-style; also runs under pytest
```

Design notes: single agent, no LLM (commands are parsed deterministically; ASI:One's own LLM
handles natural-language routing to the agent), no database. `services/swarm_engine.py` was added
to the baseline layout because the simulation is the core domain logic.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then set AGENT_SEED_PHRASE
```

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `AGENT_SEED_PHRASE` | **yes** | - | Secret. Determines the agent address. |
| `AGENT_NAME` | no | `agri-swarm-agent` | |
| `AGENT_PORT` | no | `8000` | |
| `AGENT_MAILBOX` | no | `true` | Connect to Agentverse via Mailbox |
| `LOG_LEVEL` | no | `INFO` | |
| `MAX_DRONES` | no | `200` | Per-swarm cap (1-500) |
| `MAX_TICKS_PER_REQUEST` | no | `500` | |
| `RUN_TIME_BUDGET_SECONDS` | no | `5` | Wall-clock cap for one `run` |
| `MAX_SESSIONS` / `SESSION_TTL_SECONDS` | no | `100` / `3600` | |
| `MAX_MESSAGE_CHARS` | no | `500` | |

## Run locally

```bash
python agent.py
```

The agent logs an Inspector link. For Agentverse/ASI:One access, keep `AGENT_MAILBOX=true`,
open the Inspector link, click **Connect**, choose **Mailbox**, then restart the agent
(documented flow: https://uagents.fetch.ai/docs/agentverse/mailbox). After that the agent appears
under **Local Agents** in Agentverse, where you can use its chat interface. For ASI:One, enable the
"Agents" toggle and make sure the agent is registered with a good description.

Try the logic without any network or SDK:

```bash
python -c "
from services.memory import SessionStore
from services.tools import handle_chat_text
s = SessionStore()
for t in ['add 5 drones', 'run', 'map']:
    print(handle_chat_text(s, 'me', t))
"
```

## Tests

```bash
python -m unittest discover -s tests -t . -v      # or: pytest
```

`tests/test_agent.py` uses minimal stand-ins for `uagents` when the SDK is not installed (they
only check handler wiring; with the real SDK installed those cases are skipped). All tests run
without credentials or network.

## Deployment (Agentverse)

Recommended path: **Mailbox agent** (above), since this project uses multiple modules. A fully
hosted Agentverse agent is a separate workflow and has not been set up here; check the current
Agentverse docs before attempting it (file layout and allowed libraries differ). Never upload
`.env`; provide `AGENT_SEED_PHRASE` and other settings through the platform's supported secret /
configuration mechanism.

