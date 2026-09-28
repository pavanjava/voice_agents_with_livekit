# s2s-agents — LiveKit Speech-to-Speech Voice Agents Workshop

A collection of progressively more advanced LiveKit voice agents (STT → LLM → TTS pipelines),
plus a React UI, cloud deployment example, and observability integrations. Built around
`livekit-agents` with Cartesia (STT/TTS), OpenAI (LLM), Silero (VAD), and local RAG via
LlamaIndex + Ollama + Qdrant.

## Setup

```bash
uv sync
```

Copy `.env.example`-style vars into `.env` (see `deploy_to_cloud/.env` for the shape):

```env
CARTESIA_API_KEY=...
OPENAI_API_KEY=...
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
```

For the full React UI + agent + token server run instructions, see
[ReactUI_Livekit_Integration.md](livekit-voice-ui/ReactUI_Livekit_Integration.md).

## LiveKit Local Setup

### Prerequisites

- macOS with [Homebrew](https://brew.sh/) installed

### Step 1: Install the LiveKit Server

```bash
brew install livekit
```

Verify the install:

```bash
livekit-server --version
```

### Step 2: Install the LiveKit CLI

```bash
brew install livekit-cli
```

Verify the install:

```bash
lk --version
```

### Step 3: Start LiveKit Server Locally

Run the server in **dev mode** (uses fixed default credentials, no config file needed):

```bash
livekit-server --dev
```

The server starts on `ws://localhost:7880` with the following default credentials:

| Key | Value |
|-----|-------|
| API Key | `devkey` |
| API Secret | `secret` |

> Keep this terminal open. The server runs in the foreground and must stay running while your agent is active.

### Step 4: Set Environment Variables

In your project `.env` file, use the local dev credentials:

```env
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
```

### Step 5: Run Your Agent in Console Mode

Open a new terminal tab (keep the server running in the previous one), then:

```bash
python basic_agent/agent_v1.py console
```

This starts the agent in terminal console mode — your Mac's mic and speakers are used directly, no browser needed.

### Notes

- Dev mode is for **local testing only**. Do not use `devkey`/`secret` in production.
- The `--dev` flag auto-generates a self-signed certificate and skips auth checks.
- To stop the server, press `Ctrl+C` in the terminal where it is running.

## Modules

| Module | Description |
|---|---|
| [basic_agent](basic_agent/agent_v1.py) | Minimal voice agent: Cartesia STT/TTS + OpenAI LLM, no tools, no RAG. |
| [agent_with_tools](agent_with_tools) | Adds `function_tool`s — `agent_with_realdata_1.py` does live web search (DDGS); `agent_with_realdata_2.py` adds a local RAG index (LlamaIndex + Qdrant + Ollama). |
| [agent_with_ctx](agent_with_ctx/agent_with_user_turn_and_ctx.py) | Voice agent with `ChatContext`/user-turn handling and a local RAG index. |
| [agent_with_usage_metrics](agent_with_usage_metrics/agent_with_metrics.py) | Instruments an agent with `MetricsCollectedEvent`/`AgentStateChangedEvent` to log per-stage latency (VAD/STT/LLM/TTS). |
| [agent_handoff](agent_handoff/rag_agent_handoff.py) | Multi-agent handoff pattern for RAG-backed report generation. |
| [livekit_observability](livekit_observability) | OpenTelemetry tracing exported to Langfuse (`agent_with_langfuse_observability.py`) or MLflow (`agent_with_mlflow_observability.py`). |
| [deploy_to_cloud](deploy_to_cloud) | Agent packaged for LiveKit Cloud deployment (`Dockerfile`, `livekit.toml`, own `pyproject.toml`) — see `deploy_to_cloud/deployment-instructions.md`. |
| [livekit-voice-ui](livekit-voice-ui) | React + TypeScript + Vite frontend that connects to an agent over WebRTC, plus a Node token server (`token-server.mjs`). |
| [data](data) | Sample docs (`MF_Base_OC.pdf`/`.md`) used to build the local RAG index, and a golden eval set (`golden_ds.jsonl`). |

## Running an agent

Local console mode (mic/speakers directly, no browser):

```bash
python basic_agent/agent_v1.py console
```

Worker mode (accepts WebRTC jobs, e.g. from the React UI):

```bash
python agent_with_tools/agent_with_realdata_2.py start
```

RAG-based agents (`agent_with_ctx`, `agent_with_realdata_2`, `agent_handoff`,
`agent_with_mlflow_observability`) expect a local Qdrant instance at
`http://localhost:6333` and Ollama models `embeddinggemma:latest` / `gemma3:latest` pulled.

## Related docs

- [ReactUI_Livekit_Integration.md](livekit-voice-ui/ReactUI_Livekit_Integration.md) — full 4-service run (server, agent, token server, React UI) and troubleshooting.
- [VoiceAgents_Workshop_Presentation.pptx](VoiceAgents_Workshop_Presentation.pptx) — workshop slides.
