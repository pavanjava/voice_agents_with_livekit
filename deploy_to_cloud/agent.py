import logging

from dotenv import load_dotenv, find_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions, function_tool
from livekit.plugins import cartesia, openai

load_dotenv(find_dotenv())

logger = logging.getLogger("voice-agent")


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
    session = AgentSession(
        stt=cartesia.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
    )

    await session.start(
        room=ctx.room,
        agent=GeneralAssistant(),
        room_input_options=RoomInputOptions()
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="MortgageAgent"))