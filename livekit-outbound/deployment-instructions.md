# LiveKit Voice Agent — Agent, Outbound Calling & Cloud Deployment Guide

A STT → LLM → TTS voice agent, containerized with `uv`, deployed to LiveKit Cloud, and able to place outbound phone calls through a Twilio Elastic SIP Trunk.

**Stack**: Cartesia (STT + TTS), OpenAI `gpt-4o-mini` (LLM), DuckDuckGo search as a function tool, Twilio SIP trunk for PSTN — no external dependencies like local Ollama or Qdrant, so nothing needs to be reachable from LiveKit's infrastructure.

---

## 1. Project structure

```
livekit-voice-agent/
├── agent.py
├── pyproject.toml
├── uv.lock              # generated, do not hand-write
├── Dockerfile
├── .dockerignore
├── livekit.toml         # written by `lk agent create` — project subdomain + agent id
└── .env                 # local only — never committed, never baked into the image
```

---

## 2. The agent (`agent.py`)

```python
import json
import logging
import os

from dotenv import load_dotenv, find_dotenv
from livekit import agents, api
from livekit.agents import AgentSession, Agent, RoomInputOptions, function_tool
from livekit.plugins import cartesia, openai

load_dotenv(find_dotenv())

logger = logging.getLogger("voice-agent")

# Outbound trunk ID from LiveKit (lk sip outbound list)
SIP_TRUNK_ID = os.getenv("SIP_TRUNK_ID")


@function_tool()
async def collect_realtime_data(user_query: str) -> str:
    """Use this tool to get the real data from the vector store"""
    from ddgs import DDGS
    logger.info(f"collect_realtime_data called with query: {user_query!r}")
    context = ""
    results = DDGS().text(query=user_query, max_results=5)
    logger.info(f"full context: {results}")

    for i, result in enumerate(results, start=1):
        title = result.get("title", "")
        body = result.get("body", "")
        href = result.get("href", "")
        context += f"[{i}] {title}\n{body}\nSource: {href}\n\n"

    return context.strip()


class GeneralAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=("You are a Mortgage Speciality who can answer any mortgage specific user queries."
                          "Always use the tools given to you to fetch the real time mortgage related data, "
                          "never use your prior knowledge. If any question other than mortgage is asked "
                          "reject them very politely."),
            tools=[collect_realtime_data]
        )


async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    # --- Outbound dialing -------------------------------------------------
    # The phone number arrives in the dispatch metadata, e.g.
    #   lk dispatch create --new-room --agent-name MortgageAgent \
    #       --metadata '{"phone_number": "+91XXXXXXXXXX"}'
    # If no number is present (web/mobile session), the agent behaves as before.
    phone_number = None
    if ctx.job.metadata:
        try:
            dial_info = json.loads(ctx.job.metadata)
            phone_number = dial_info.get("phone_number")
        except json.JSONDecodeError:
            logger.warning(f"could not parse job metadata: {ctx.job.metadata!r}")

    participant = None
    if phone_number:
        if not SIP_TRUNK_ID:
            logger.error("SIP_TRUNK_ID is not set; cannot place outbound call")
            ctx.shutdown()
            return

        logger.info(f"dialing {phone_number} via trunk {SIP_TRUNK_ID}")
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=SIP_TRUNK_ID,
                    sip_call_to=phone_number,
                    participant_identity=phone_number,
                    participant_name="Callee",
                    # Block until the callee picks up; raises SipCallError otherwise
                    wait_until_answered=True,
                )
            )
            logger.info("call answered")
        except api.SipCallError as e:
            # 486/603 = rejected, 408/480 = no answer, 5xx = trunk failure
            logger.error(f"call failed: {e.sip_status_code} {e.sip_status}")
            ctx.shutdown()
            return

        # Make sure the SIP participant is fully in the room before starting
        participant = await ctx.wait_for_participant(identity=phone_number)
        logger.info(f"SIP participant joined: {participant.identity}")
    # ----------------------------------------------------------------------

    session = AgentSession(
        stt=cartesia.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
    )

    await session.start(
        room=ctx.room,
        agent=GeneralAssistant(),
        participant=participant,  # None for web sessions -> auto-detect
        room_input_options=RoomInputOptions(),
    )

    # On outbound calls the callee speaks first ("Hello?"), so no greeting here.
    # For web/mobile sessions, greet proactively.
    if phone_number is None:
        await session.generate_reply(
            instructions="Greet the user briefly and offer help with mortgage questions."
        )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="MortgageAgent"))
```

Notes:
- `await ctx.connect()` is required — without it the agent never actually joins the room even though it registers as a worker. For outbound calls it matters even more: `ctx.wait_for_participant` needs a connected room.
- `agent_name="MortgageAgent"` **is set intentionally.** Outbound calling relies on explicit dispatch — the phone number travels in the dispatch metadata — so automatic dispatch to new rooms is off. Web/mobile sessions must also be dispatched explicitly (see section 10).
- The dial happens *before* `AgentSession` is created, and `wait_until_answered=True` blocks until the callee picks up. This guarantees the session (and any TTS) only starts once a human is on the line.
- On a failed dial the agent calls `ctx.shutdown()` to release the job. Voicemail answers with `200 OK` and is *not* a failure — add LiveKit's answering machine detection if you need to distinguish it.

---

## 3. `pyproject.toml`

```toml
[project]
name = "livekit-voice-agent"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "livekit-agents[cartesia, openai]",
    "python-dotenv",
    "qdrant-client>=1.18.0",
    "fastembed>=0.8.0",
    "ddgs>=9.14.4",
    "livekit>=1.1.12",
    "requests>=2.34.2"
]
```

Don't hand-write `uv.lock`. Let `uv lock` / `uv sync` generate it.

---

## 4. `.dockerignore`

```
.venv
__pycache__
*.pyc
.env
.git
.gitignore
```

`uv.lock` is committed and copied into the image (see the Dockerfile), so it is **not** ignored here.

---

## 5. `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1

# --- Build stage ---
FROM base AS build

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --locked

RUN uv run --module livekit.agents download-files

# Copy application code
COPY agent.py ./

# --- Production stage ---
FROM base

ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/app" \
    --shell "/sbin/nologin" \
    --uid "${UID}" \
    appuser

WORKDIR /app

COPY --from=build --chown=appuser:appuser /app /app

USER appuser

CMD ["uv", "run", "agent.py", "start"]
```

**Do not `COPY .env ./` into the image.** LiveKit Cloud's deploy flow reads your local `.env` at deploy time and uploads its contents as managed secrets, injecting them as real environment variables into the running container. Baking `.env` into the image is both redundant and will actively break LiveKit Cloud's remote build step (it doesn't forward `.env` into that build context the way local Docker does).

---

## 6. Environment variables

Local `.env` (used for `uv run agent.py dev` / `console` testing, and read by the LiveKit CLI when deploying):

```bash
LIVEKIT_URL=wss://yourproject.livekit.cloud
LIVEKIT_API_KEY=your_cloud_api_key
LIVEKIT_API_SECRET=your_cloud_api_secret

OPENAI_API_KEY=your_openai_key
CARTESIA_API_KEY=your_cartesia_key

# Outbound trunk (from `lk sip outbound list`, or Telephony → SIP trunks in the dashboard)
SIP_TRUNK_ID=ST_xxxxxxxxxxxx
```

Get the LiveKit values from your project dashboard at https://cloud.livekit.io → **Settings → API keys**. `SIP_TRUNK_ID` is read by `agent.py` at startup; keeping it in the environment lets you swap trunks (a different edge, a different carrier) without touching code.

---

## 7. Telephony setup (Twilio → LiveKit)

One-time setup. Once done, the agent needs only the `ST_…` trunk ID.

### 7.1 Twilio

1. **Account** — upgraded (not trial) and a Compliance Profile approved. Twilio requires the profile for accounts outside the US before any number can be held.
2. **Number** — buy a US **Local** number with Voice capability. Toll-free numbers don't work for SIP termination. The "Finish setting up your number" items (SHAKEN/STIR, Voice Integrity, Branded Calling, CNAM) are US-carrier reputation features and can be skipped.
3. **Geo Permissions** — Voice → Settings → Geo permissions: enable every destination country you will call (e.g. India). Without this Twilio answers the INVITE with `403`.
4. **Elastic SIP Trunk** — Elastic SIP Trunking → Trunks → Create:
   - **Termination** tab: set a Termination SIP URI (`<name>.pstn.twilio.com`). Note the full domain.
   - **Termination → Authentication**: create a Credential List (username + strong password) and attach it. Leave IP ACLs empty — LiveKit Cloud egress IPs are not fixed.
   - **Numbers** tab: attach the number you bought. It becomes the caller ID.
   - Origination tab is inbound-only; leave it.

### 7.2 LiveKit Cloud

Telephony → SIP trunks → Create new trunk → direction **Outbound**:

| Field | Value |
|---|---|
| name | `twilio-outbound` |
| address | `<name>.pstn.twilio.com` |
| numbers | `["+1XXXXXXXXXX"]` (E.164) |
| authUsername / authPassword | from the Twilio Credential List |

The result is a trunk ID `ST_…`. Put it in `.env` as `SIP_TRUNK_ID`. Verify with `lk sip outbound list`.

---

## 8. Test locally against LiveKit Cloud first

Before deploying, confirm the agent works pointed at your real cloud project (not local dev mode):

```bash
uv sync
uv run agent.py dev
```

This connects using the `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` in your `.env`, so you're validating against the actual cloud project, just running the worker process on your machine. Leave it running.

### Place a test call

From a second terminal:

```bash
lk dispatch create \
  --new-room \
  --agent-name MortgageAgent \
  --metadata '{"phone_number": "+91XXXXXXXXXX"}'
```

Expected log sequence: `dialing +91… via trunk ST_…` → phone rings → `call answered` → `SIP participant joined` → say "Hello" and the agent responds.

Check the call in **LiveKit Cloud → Telephony → Calls** and **Twilio → Monitor → Logs → Calls**.

| Log line | Meaning | Action |
|---|---|---|
| `call failed: 486` / `603` | Busy / declined | Retry later |
| `call failed: 408` / `480` | No answer / unreachable | Retry later |
| `call failed: 403` | Twilio rejected the INVITE | Check Geo Permissions and the credential-list username/password |
| `call failed: 5xx` | Trunk / protocol failure | Check termination URI and that the number is attached to the Twilio trunk |

---

## 9. Deploy to LiveKit Cloud

Install the LiveKit CLI if you haven't already:

```bash
curl -sSL https://get.livekit.io/cli | bash
```

Authenticate and link the project:

```bash
lk cloud auth
```

From the project root (where the `Dockerfile` lives), first time only:

```bash
lk agent create
```

This will:
1. Prompt you to select a secrets file — point it at your `.env`. LiveKit Cloud stores these as managed secrets (including `SIP_TRUNK_ID`) and injects them at container runtime.
2. Build the Docker image remotely using your `Dockerfile`.
3. Push and deploy the worker to LiveKit Cloud's agent infrastructure.
4. Write `livekit.toml` with the project subdomain and agent id.

Watch the build logs for a line confirming the worker registered successfully with LiveKit Cloud — that means it's live and listening for room dispatches.

To redeploy after code changes (uses `livekit.toml`, so the existing agent is updated rather than a new one created):

```bash
lk agent deploy
```

To check status or logs:

```bash
lk agent status
lk agent logs
```

After deploying, the same `lk dispatch create …` command from section 8 places calls through the cloud-hosted worker.

---

## 10. Test the deployed agent from a browser

Because `agent_name` is set, the agent is not auto-dispatched. Create a room and dispatch it without a phone number:

```bash
lk dispatch create --new-room --agent-name MortgageAgent
```

then join that room from the [LiveKit Agents Playground](https://agents-playground.livekit.io/) — it lets you talk to the deployed agent through the browser via WebRTC, with no custom frontend needed. In this mode the agent greets first.

---

## 11. Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Docker build fails on `COPY .env ./` | LiveKit Cloud's remote builder doesn't forward `.env` into build context | Remove the line; let LiveKit Cloud inject secrets at runtime instead |
| `uv sync --locked` fails with "lock file not found" | `uv.lock` wasn't committed/copied but Dockerfile assumes it exists | Commit `uv.lock` (and keep it out of `.dockerignore`) |
| Agent builds and deploys but never joins rooms | Missing `await ctx.connect()` in `entrypoint` | Add the connect call before dialing / starting the session |
| Agent registers as a worker but never gets dispatched to new rooms | `agent_name=` set in `WorkerOptions` (blocks auto-dispatch) | Expected here — dispatch explicitly with `lk dispatch create` |
| `SIP_TRUNK_ID is not set` in logs | Secret missing from the deployed agent | Add it to `.env` and redeploy so it is uploaded as a managed secret |
| `call failed: 403` | Destination country not enabled, or wrong trunk credentials | Twilio Geo Permissions; username/password must match the Credential List exactly |
| Callee answers but hears silence for a moment | Session started before the SIP participant joined | Keep `wait_until_answered=True` and `wait_for_participant` before `session.start` |
| Call "succeeds" but agent is talking to voicemail | Voicemail answers with `200 OK` | Enable LiveKit answering machine detection |
| TTS calls intermittently time out on longer responses | Tool/LLM returning very large text blocks for TTS to synthesize | Trim what gets spoken back; keep tool output out of the final spoken response where possible |

---

## 12. Next steps once this is stable

- **Hang up cleanly** — add LiveKit's prebuilt `EndCallTool` to the agent's tools so it can end the call when the conversation is over; otherwise the callee hears silence until they hang up.
- **Latency** — switch the LiveKit trunk address to the Twilio edge nearest the callee (e.g. `<name>.pstn.singapore.twilio.com` for India).
- **Answering machine detection** — classify human vs voicemail vs IVR and respond accordingly.
- **Secure trunking** — enable TLS/SRTP on the Twilio trunk once the basic call path is confirmed.
- **Concurrency** — Twilio caps calls-per-second and concurrent calls until a Business Profile is approved.
- Add observability (e.g. Langfuse via OpenTelemetry) — note that `opentelemetry-sdk` must be pinned `>=1.30,<1.39` for compatibility with current `livekit-agents` telemetry imports (`LogData` was removed in 1.39.0).