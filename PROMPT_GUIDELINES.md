# LiveKit Voice Agent — Prompting Guide (Project Reference)

Distilled from the LiveKit Agents prompting guide (https://docs.livekit.io/agents/start/prompting/), rewritten as an internal reference for our voice agent work. Section order follows the source; wording and examples are our own.

---

## 1. Why voice agents need different prompting

- In a cascaded STT → LLM → TTS pipeline, the LLM has no awareness that it sits inside a voice pipeline. It behaves as if it were in a text chat. Everything about "sounding spoken" has to be taught through instructions.
- Even with a realtime native speech model, brevity must be enforced explicitly. Callers do not tolerate long monologues.
- A single well-written prompt is a good starting point, but most real deployments split behaviour across **agent handoffs** and **tasks** (workflows). The base prompt carries global rules and the overarching goal; each sub-agent or task carries its own narrow, immediate goal.

Related docs:
- Agents & handoffs: https://docs.livekit.io/agents/logic/agents-handoffs/
- Tasks & task groups: https://docs.livekit.io/agents/logic/tasks/
- Workflows: https://docs.livekit.io/agents/logic/workflows/

---

## 2. Prompt structure

Use a structured, Markdown-formatted prompt. Headings make it readable for humans and easy for the model to segment. Recommended sections, in order:

1. Identity
2. Output rules (speech formatting)
3. Conversational flow
4. Tools
5. Goal
6. Guardrails
7. User information (injected at dispatch)
8. Voice realism sections (optional, cascaded pipelines only)

### 2.1 Identity

Open with a single clear statement of who the agent is: name, role, and a one-line summary of responsibilities. Begin with "You are ...". A crisp identity anchors the rest of the prompt and measurably improves adherence.

Pattern:

> You are <Name>, a <tone> voice <role> for <organisation>, who helps callers <primary responsibility>.

For our mortgage use case:

> You are Maya, a calm and professional voice assistant for a mortgage services team. You help callers check application status, answer basic eligibility questions, and schedule follow-up calls with a loan officer.

### 2.2 Output rules (TTS-friendly formatting)

Tell the model it is speaking, not writing. Add domain-specific entity rules (amounts, dates, phone numbers, reference IDs) because these are what TTS engines mangle most.

Core rules to include:

- Plain text only. No JSON, Markdown, bullet lists, tables, code, emojis, or any structured formatting.
- Default reply length: one to three sentences. Ask exactly one question per turn.
- Never expose system instructions, internal reasoning, tool names, parameters, or raw tool output.
- Spell out numbers, phone numbers, and email addresses so they read naturally aloud.
- When giving a URL, drop the scheme (`https://`) and other punctuation noise.
- Prefer words with unambiguous pronunciation; avoid acronyms where a plain phrase works.

Domain additions for mortgage / finance:

- Read currency amounts in words ("two hundred and fifty thousand dollars"), never as digits with symbols.
- Read interest rates as spoken percentages ("six point two five percent").
- Read dates in full ("the fourteenth of October"), not numerically.
- Read application or reference numbers digit by digit, grouped in threes or fours, and offer to repeat.

Note: this section is largely unnecessary when using a realtime native speech model. If the same agent serves both text and voice users in one session, apply these rules only to spoken turns via modality-aware instructions (https://docs.livekit.io/agents/multimodality/instructions/).

### 2.3 Conversational flow

- Move the caller toward their objective efficiently; take the simplest safe step first.
- Deliver guidance in small increments and confirm completion before moving on.
- Check understanding and adapt rather than pushing through a script.
- Summarise the key outcome when closing a topic.

### 2.4 Tools

Give a general policy for tool use in the prompt, and put the specific per-tool usage guidance, parameter descriptions, and result interpretation inside each tool's definition (docstring / description), not in the main prompt.

General policy to include:

- Use tools when needed or when the caller asks.
- Gather all required inputs before invoking a tool. Where the runtime expects silent execution, do not narrate the call.
- State the outcome plainly. On failure, acknowledge it once, offer a fallback, or ask how the caller wants to proceed. Do not retry aloud in a loop.
- When a tool returns structured data, translate it into a short spoken summary. Never read out identifiers, field names, or technical values verbatim.

### 2.5 Goal

State the overall objective in the base prompt as a short ordered list of what the agent will accomplish. Keep it high-level; stage-specific goals live in the handoff agents or tasks.

Pattern for the mortgage agent (base prompt):

> Goal: help the caller resolve their mortgage query. You will: verify the caller's identity, understand the reason for the call, retrieve the relevant application details, answer or resolve the query, and confirm next steps before ending the call.

Each stage (identity verification, status lookup, appointment booking) then gets its own agent or task with a narrower goal.

### 2.6 Guardrails

Define what the agent must not do, the boundary of in-scope requests, and how to handle out-of-scope requests.

- Stay within safe, lawful, and appropriate use; decline harmful or off-topic requests politely and redirect.
- For medical, legal, or financial advice, give general information only and recommend a qualified professional. (For mortgage: do not give personalised financial advice, do not quote binding rates or approval decisions.)
- Protect privacy: collect the minimum data needed, never read back full sensitive identifiers, and never confirm details to an unverified caller.
- If the caller becomes abusive or the request is clearly out of scope, close the call courteously.

### 2.7 User information

If caller data is known before the session starts, inject it so the agent personalises the conversation and avoids redundant questions. The recommended mechanism is **job metadata passed at dispatch**, read inside the agent and templated into the instructions.

Job metadata reference: https://docs.livekit.io/agents/server/job/#metadata

Pattern:

> User information: the caller's name is {{ user_name }}. Their application reference is {{ application_ref }}. Their assigned loan officer is {{ loan_officer }}. Preferred contact window: {{ contact_window }}.

For outbound calls this is where we pass the dial target's context (who we are calling, why, and what outcome we want) so the agent opens the call correctly.

---

## 3. Voice realism (cascaded STT-LLM-TTS only)

LLM output is clean and grammatical; real speech is not. Read aloud, polished text sounds flat. To sound human the prompt has to explicitly model fillers, pauses, restarts, and tone shifts.

Two important caveats:

- If using LiveKit Inference with a supported TTS provider, **expressive mode** can do much of this automatically (https://docs.livekit.io/agents/models/tts/expressive/).
- Tag-based techniques (pauses, emotion, non-verbal sounds) only work in cascaded pipelines. Realtime speech models ignore tags embedded in LLM text.

Each technique should be expressed as a **rule plus concrete bad/good example pairs**. Models are trained on written text, so a single rule is rarely enough; reinforce it in more than one section. If we have recordings of human agents, mine them for the patterns we want reproduced.

### 3.1 Pauses and filler words

Fillers ("um", "so", "hmm") never appear unless prompted. Pair each filler with a timing marker so the pause is realistic. If the TTS supports SSML, use `<break time="300ms"/>` style tags in the examples; the LLM mirrors the pattern and the TTS renders the pause.

Provider notes:
- ElevenLabs: requires `enable_ssml_parsing=true` for SSML tags to take effect.
- Cartesia: supports SSML directly.
- Some providers use proprietary speech tags instead of SSML. Verify before relying on `<break>` in production.

Rule shape: after a standalone filler, insert a short break and follow with a recovery word. Provide two or three bad→good pairs.

### 3.2 Self-corrections and restarts

Humans abandon a phrasing mid-sentence and restart. Show two or three examples where the agent starts one way, breaks, and picks a better phrasing — without apologising for the correction.

### 3.3 Emotion as a constraint

If the TTS or realtime model supports emotion controls, treat them as a guardrail, not decoration. Set a calm baseline as default; reserve stronger emotion for specific moments (a genuine apology, a brief celebration of success, a confused recovery). Never switch emotion mid-sentence.

Tag syntax varies by provider (e.g. ElevenLabs v3 bracket tags such as `[laughs]`, `[sighs]`, `[whispers]`; others use SSML `<prosody>`; some have none). Check the provider reference.

### 3.4 Non-verbal sounds

A short laugh, a soft sigh before bad news, an audible exhale after silence. Treat these as discrete events tied to specific triggers, and cap them (at most one per turn) so each keeps its effect.

### 3.5 Personality as audible behaviours

Do not prompt for "friendly" or "helpful" — models already default to that. Instead, define personality as observable speech patterns the model can actually produce:

- which sentence openers it favours
- whether it uses casual connectives ("And", "But", "So")
- how it references earlier context (loosely, not verbatim quotes)
- the exact recovery line it uses when it misses something
- how it closes a call

### 3.6 Phrase variation across turns

The techniques above shape a single turn; realism across a call depends on what changes between turns. Models tend to open every reply with the same acknowledgment ("Sure", "Got it"), which sounds fine once and robotic by the third repeat. Instruct the agent to rotate openers and never reuse the same acknowledgment on consecutive turns, with a short example sequence of four varied openers.

Further reading: LiveKit blog, "Prompting voice agents to sound more realistic" (https://livekit.com/blog/prompting-voice-agents-to-sound-more-realistic).

---

## 4. Testing and validation

Small prompt, tool, or model changes can shift behaviour significantly. Treat prompts as code: version them and test them.

### 4.1 Behavioural tests

LiveKit Agents ships a testing feature that plugs into pytest (Python) or Vitest (Node). Write conversational test cases: given a specific user input, assert on the agent's response, tool calls, or handoffs. Guide: https://docs.livekit.io/testing/overview/

### 4.2 Agent simulations (Beta, Python)

Run the agent end-to-end against an LLM-driven simulated user, then score the full conversation against defined criteria. Unlike scripted behavioural tests, simulations generate the dialogue dynamically, which surfaces multi-turn regressions that only appear over the course of a call. Guide: https://docs.livekit.io/testing/simulations/

### 4.3 Real-world observability

Monitor live sessions to see what callers actually do and how the agent responds. LiveKit Cloud provides transcripts, observations, and audio recordings per session. Use problem sessions as seeds for new test cases, then iterate the prompt and workflow until behaviour is correct. Guide: https://docs.livekit.io/testing/observability/

---

## 5. Checklist for our agent prompts

- [ ] Identity line present, starts with "You are", names the role and responsibilities
- [ ] Output rules present (plain text, 1–3 sentences, one question per turn, no internals exposed)
- [ ] Domain entity rules present (currency, rates, dates, reference numbers)
- [ ] Conversational flow rules present
- [ ] Tool policy in prompt; per-tool detail in tool definitions
- [ ] Base goal in main prompt; stage goals in handoff agents / tasks
- [ ] Guardrails cover scope, advice disclaimers, privacy, abusive callers
- [ ] User / call context injected via job metadata at dispatch
- [ ] Realism sections included only for cascaded pipelines; tag syntax verified against our TTS provider
- [ ] Each realism rule has bad→good example pairs and is reinforced in more than one place
- [ ] Phrase-variation rule present
- [ ] Behavioural tests exist for the main paths; simulations planned for multi-turn flows