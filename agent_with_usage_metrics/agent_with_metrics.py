"""
Each time the agent starts speaking, you'll see the time to first audio log.
Here's a reference again for what to expect:

Component	Best case	Typical
VAD	        15-20ms	    20-30ms
STT	        200-300ms	400-600ms
LLM	        100-200ms	500-1000ms
TTS	        100-150ms	200-300ms
Total	      ~415ms	1.1s-2s
"""
import time
import logging
from livekit import agents
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    MetricsCollectedEvent,
    metrics,
    room_io, AgentStateChangedEvent
)
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import openai, cartesia
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

logger = logging.getLogger(__name__)

class GenericAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=("You are a conversational agent you can talk with user on any topic that user initiate with you."
                          "You dont have any boundaries or restrictions on the topics that you can speak. "
                          "but the conversation should be very polite and the topic oriented and topic bounded."),
            tools=[EndCallTool()]
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(instructions="Greet the user and introduce yourself.")

server = AgentSession()

async def entrypoint(ctx: JobContext) -> None:

    # Aggregate data across all conversation turns
    usage_collector = metrics.UsageCollector()

    # Track End of Utterance timing (when turn detector decides user finished speaking)
    last_eou_metrics: metrics.EOUMetrics | None = None

    # each log entry will include these fields
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session: AgentSession = AgentSession(
        stt=cartesia.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
        preemptive_generation=True # Test with both options (True, False) to see the variation in metrics
    )

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent) -> None:
        nonlocal last_eou_metrics
        # Capture EOU metrics for TTFA calculation
        if ev.metrics.type == "eou_metrics":
            last_eou_metrics = ev.metrics

        # Log each metric as it arrives and add to usage collector
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    @session.on("agent_state_changed")
    def _on_agent_state_changed(ev: AgentStateChangedEvent):
        if ev.new_state == "speaking":
            if last_eou_metrics:
                # Calculate time since user finished speaking
                elapsed = time.time() - last_eou_metrics.timestamp
                logger.info(f"Time to first audio: {elapsed:.3f}s")

    async def log_usage():
        # Print per-session summary (tokens, audio duration, costs)
        summary = usage_collector.get_summary()
        logger.info("Usage summary: %s", summary)

    # shutdown callbacks are triggered when the session is over
    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=GenericAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # uncomment to enable the Krisp BVC noise cancellation
                # noise_cancellation=noise_cancellation.BVC(),
            ),
        ),
    )

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint)) # agent_name="<YOUR NAME>"