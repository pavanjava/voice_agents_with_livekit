# LiveKit Voice Agent — Simple Agent & Cloud Deployment Guide

A minimal STT → LLM → TTS voice agent, containerized with `uv`, and deployed to LiveKit Cloud.

**Stack**: Cartesia (STT + TTS), OpenAI `gpt-4o-mini` (LLM), Silero (VAD) — no tools, no external dependencies like local Ollama or Qdrant, so nothing needs to be reachable from LiveKit's infrastructure.

---

## 1. Project structure

```
livekit-voice-agent/
├── agent.py
├── pyproject.toml
├── uv.lock              # generated, do not hand-write
├── Dockerfile
├── .dockerignore
└── .env                 # local only — never committed, never baked into the image
```

---

## 2. The agent (`agent.py`)

```python
import logging

from dotenv import load_dotenv, find_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import cartesia, openai, silero

load_dotenv(find_dotenv())

logger = logging.getLogger("voice-agent")


class GeneralAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "You are a helpful voice assistant. Keep your responses "
                "concise and conversational, since they will be spoken aloud."
            ),
        )


async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    session = AgentSession(
        stt=cartesia.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
        vad=silero.VAD.load(),
    )

    await session.start(
        room=ctx.room,
        agent=GeneralAssistant(),
        room_input_options=RoomInputOptions(),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
```

Notes:
- `await ctx.connect()` is required — without it the agent never actually joins the room even though it registers as a worker.
- Don't set `agent_name=` in `WorkerOptions` unless you intend to do explicit dispatch — setting it blocks LiveKit's automatic dispatch to new rooms.
- No tools are wired in here on purpose. Add them back once the bare pipeline is confirmed working in the cloud.

---

## 3. `pyproject.toml`

```toml
[project]
name = "livekit-voice-agent"
version = "0.0.1"
requires-python = ">=3.12"
dependencies = [
    "livekit-agents[cartesia, openai, silero]",
    "python-dotenv",
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
uv.lock
```

Excluding `uv.lock` here is optional — see the Dockerfile note below on whether you commit and copy it or regenerate it at build time.

---

## 5. `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1

WORKDIR /app

# Copy only dependency manifests first so Docker can cache this layer
COPY pyproject.toml ./

# Generates uv.lock during the build and installs dependencies.
# If you commit uv.lock and want reproducible installs instead, copy it in
# above and use `RUN uv sync --frozen` here.
RUN uv sync

# Now copy the actual application code
COPY agent.py ./

# Pre-download model files (e.g. Silero VAD weights) so cold start doesn't
# fetch them on first job — LiveKit agents support a "download-files" step
RUN uv run agent.py download-files

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
```

Get the LiveKit values from your project dashboard at https://cloud.livekit.io → **Settings → Keys**.

---

## 7. Test locally against LiveKit Cloud first

Before deploying, confirm the agent works pointed at your real cloud project (not local dev mode):

```bash
uv sync
uv run agent.py console
```

This connects using the `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` in your `.env`, so you're validating against the actual cloud project, just running the worker process on your machine.

---

## 8. Deploy to LiveKit Cloud

Install the LiveKit CLI if you haven't already:

```bash
curl -sSL https://get.livekit.io/cli | bash
```

Authenticate and link the project:

```bash
lk cloud auth
```

From the project root (where the `Dockerfile` lives):

```bash
lk agent create
```

This will:
1. Prompt you to select a secrets file — point it at your `.env`. LiveKit Cloud stores these as managed secrets and injects them at container runtime.
2. Build the Docker image remotely using your `Dockerfile`.
3. Push and deploy the worker to LiveKit Cloud's agent infrastructure.

Watch the build logs for a line confirming the worker registered successfully with LiveKit Cloud — that means it's live and listening for room dispatches.

To redeploy after code changes:

```bash
lk agent deploy
```

To check status or logs:

```bash
lk agent status
lk agent logs
```

---

## 9. Test the deployed agent

Use the [LiveKit Agents Playground](https://agents-playground.livekit.io/) — point it at your cloud project URL and it lets you talk to the deployed agent through the browser via WebRTC, with no custom frontend needed.

---

## 10. Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Docker build fails on `COPY .env ./` | LiveKit Cloud's remote builder doesn't forward `.env` into build context | Remove the line; let LiveKit Cloud inject secrets at runtime instead |
| `uv sync --frozen` fails with "lock file not found" | `uv.lock` wasn't committed/copied but Dockerfile assumes it exists | Either commit `uv.lock` and `COPY` it in, or drop `--frozen` and just run `uv sync` to generate it at build time |
| Agent builds and deploys but never joins rooms | Missing `await ctx.connect()` in `entrypoint` | Add the connect call before starting the session |
| Agent registers as a worker but never gets dispatched to new rooms | `agent_name=` set in `WorkerOptions` (blocks auto-dispatch) | Remove `agent_name` unless you're doing explicit dispatch intentionally |
| TTS calls intermittently time out on longer responses | Tool/LLM returning very large text blocks for TTS to synthesize | Trim what gets spoken back; keep tool output out of the final spoken response where possible |

---

## 11. Next steps once this is stable

- Re-introduce tools (function calling) once the bare pipeline is confirmed working end-to-end in the cloud.
- Add observability (e.g. Langfuse via OpenTelemetry) — note that `opentelemetry-sdk` must be pinned `>=1.30,<1.39` for compatibility with current `livekit-agents` telemetry imports (`LogData` was removed in 1.39.0).
- Consider SIP trunk integration (e.g. Twilio) if you need inbound/outbound phone calling on top of the WebRTC agent.