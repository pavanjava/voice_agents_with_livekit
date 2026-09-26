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
    from tavily import TavilyClient, TavilyKeylessLimitError
    
    context = ""
    # No API key needed
    client = TavilyClient(api_key=os.environ.get('TAVILY_API_KEY'))

    try:
        response = client.search(query=user_query, search_depth='advanced', max_results=5)
        for i, result in enumerate(response.get("results", []), start=1):
            title = result.get("title", "")
            content = result.get("content", "")
            url = result.get("url", "")
            context += f"[{i}] {title}\n{content}\nSource: {url}\n\n"

    except TavilyKeylessLimitError as e:
        # Rate-limit cap reached. The exception carries the human-readable
        # message plus structured fields (code, window, retry_after_seconds,
        # next_actions) returned by the Tavily API.
        print(e)
        print("retry after:", e.retry_after_seconds, "seconds")

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
        except api.TwirpError as e:
            # 486/603 = rejected, 408/480 = no answer, 403 = carrier forbade, 5xx = trunk failure
            sip_code = e.metadata.get("sip_status_code")
            sip_status = e.metadata.get("sip_status")
            logger.error(f"call failed: {sip_code} {sip_status} ({e.message})")
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

    # Bind the session's audio input to the SIP participant on outbound calls;
    # for web sessions leave participant_identity unset so LiveKit auto-detects.
    room_input_options = RoomInputOptions()
    if participant is not None:
        room_input_options = RoomInputOptions(participant_identity=participant.identity)

    await session.start(
        room=ctx.room,
        agent=GeneralAssistant(),
        room_input_options=room_input_options,
    )

    # On outbound calls the callee speaks first ("Hello?"), so no greeting here.
    # For web/mobile sessions, greet proactively.
    if phone_number is None:
        await session.generate_reply(
            instructions="Greet the user briefly and offer help with mortgage questions."
        )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="MortgageAgent"))