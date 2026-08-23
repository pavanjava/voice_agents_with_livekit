# LiveKit Voice Agent + React UI — Run Instructions

A voice agent (Cartesia STT/TTS + OpenAI LLM) connected to a React + TypeScript
frontend over WebRTC, using a local LiveKit dev server and a Node token server.

## Architecture

Four services run simultaneously, each in its own terminal tab:

| Service         | Command                    | Port  |
|-----------------|----------------------------|-------|
| LiveKit server  | `livekit-server --dev`     | 7880  |
| Python agent    | `python agent_v2.py start` | 8081  |
| Token server    | `node token-server.mjs`    | 3001  |
| React UI (Vite) | `npm run dev`              | 5173  |

---

## Prerequisites

- macOS with [Homebrew](https://brew.sh/)
- Python 3.10+ and a virtual environment
- Node.js 18+

---

## Step 1: Install and start LiveKit server (local dev)

```bash
brew install livekit livekit-cli
livekit-server --dev
```

Keep this terminal open. It starts on `ws://localhost:7880` with default dev credentials:

| Key        | Value    |
|------------|----------|
| API Key    | `devkey` |
| API Secret | `secret` |

---

## Step 2: Set up and run the Python agent

In the agent project folder, create/activate a virtualenv and install dependencies, then set `.env`:

```env
CARTESIA_API_KEY=sk_car_...
OPENAI_API_KEY=sk-proj-...

LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
```

> Do **not** set `agent_name` in `WorkerOptions` for local testing — it disables
> auto-dispatch, so the agent won't join rooms created by the token server unless
> explicitly dispatched by name.

Start the agent in a new terminal tab:

```bash
python agent.py start
```

Wait for `registered worker` in the logs — that confirms it's connected to the local LiveKit server and ready to accept jobs.

---

## Step 3: Start the token server

In the `livekit-voice-ui` project folder:

```bash
npm install livekit-server-sdk
node token-server.mjs
```

Verify it's working:

```bash
curl http://localhost:3001/token
```

You should get back JSON with `token`, `url`, `roomName`, and `identity`.

---

## Step 4: Start the React UI

Still in `livekit-voice-ui`:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

---

## Step 5: Use it

1. Confirm all four terminals are running (server, agent, token server, Vite).
2. In the browser, click the mic button in the center of the page.
3. Grant microphone permission when prompted.
4. The agent should join the room and greet you — watch the agent terminal for `received job request` / STT transcripts confirming the connection.

---

## Troubleshooting

- **No job assigned when clicking mic:** make sure `agent_name` is not set in `WorkerOptions`, and that the agent is running in `start` mode (not `console` mode — console mode uses your Mac's local mic directly and won't accept WebRTC connections).
- **`.env` parse errors:** every line must be a valid `KEY=value` pair or start with `#` — plain comment text without `#` will break `python-dotenv`.
- **To stop any service:** `Ctrl+C` in its terminal.

---

## Notes

- `devkey` / `secret` are dev-only defaults — never use them in production.
- The `--dev` flag on `livekit-server` skips auth checks and uses a self-signed cert; it's for local testing only.