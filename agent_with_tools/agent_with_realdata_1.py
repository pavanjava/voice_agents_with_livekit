import logging

from ddgs import DDGS
from dotenv import load_dotenv, find_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions, function_tool
from livekit.plugins import cartesia, openai, silero

from livekit.agents.beta.tools import EndCallTool

load_dotenv(find_dotenv())

logger = logging.getLogger("voice-agent")


@function_tool()
async def collect_realtime_data(user_query: str) -> str:
    """Use this tool to get the real data from the internet"""
    logger.info(f"collect_realtime_data called with query: {user_query!r}")
    context = ""
    with DDGS() as ddgs:
        for result in ddgs.text(query=user_query, max_results=10):
            context = context + result.get('body', '')+". \n"

    logger.info(f"collect_realtime_data called with context: {context}")
    return context


class GeneralAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=("You are a User Personal assistant who can assist "
                          "user by collecting realtime data and responding as a news feed."
                          "always make use of the tools given to you for fetching the latest information"),
            tools=[collect_realtime_data, EndCallTool()]
        )

async def entrypoint(ctx: agents.JobContext):

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
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="MortgageAgent"))