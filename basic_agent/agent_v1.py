import logging

from dotenv import load_dotenv, find_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import cartesia, openai


load_dotenv(find_dotenv())

logger = logging.getLogger("voice-agent")


class GeneralAssistant(Agent):
    def __init__(self):
        super().__init__(
            instructions=("You are a conversational agent you caht with user on any topic that user initiate with you."
                          "You dont have any boundaries or restrictions on the topics that you can speak. "
                          "but the conversation should be very polite and the topic oriented and topic bounded"),
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