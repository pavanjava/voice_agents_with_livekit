import logging
import os
import base64

from livekit import agents
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    SessionUsageUpdatedEvent,
    inference
)
from livekit.agents.beta.tools import EndCallTool
from livekit.plugins import openai, cartesia, silero
from livekit.agents.telemetry import set_tracer_provider
from dotenv import load_dotenv, find_dotenv

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.util.types import AttributeValue

load_dotenv(find_dotenv())

logger = logging.getLogger(__name__)

def setup_langfuse(metadata: dict[str, AttributeValue] | None = None) -> TracerProvider:
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    base_url = os.environ.get("LANGFUSE_HOST")

    if not public_key or not secret_key or not base_url:
        raise ValueError("LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL must be set")

    langfuse_auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()

    logger.info(f"LANGFUSE_HOST: {base_url.rstrip('/')}/api/public/otel")
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = f"{base_url.rstrip('/')}/api/public/otel"
    os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Basic {langfuse_auth},x-langfuse-ingestion-version=4"

    trace_provider = TracerProvider()
    trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    set_tracer_provider(trace_provider, metadata=metadata)
    return trace_provider

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
    # each log entry will include these fields
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # --- Langfuse tracing setup ---
    # `langfuse.session.id` groups all spans for this call under one trace in Langfuse.
    trace_provider = setup_langfuse(
        metadata={"langfuse.session.id": ctx.room.name}
    )

    async def flush_trace():
        trace_provider.force_flush()

    ctx.add_shutdown_callback(flush_trace)
    # --- end Langfuse setup ---

    session: AgentSession = AgentSession(
        stt=cartesia.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(),
        turn_detection="vad",
        vad=inference.VAD(
            model="silero",
            min_silence_duration=0.125
        )
    )

    @session.on("session_usage_updated")
    def on_session_usage_updated(ev: SessionUsageUpdatedEvent):
        for usage in ev.usage.model_usage:
            print(f"{usage.provider}/{usage.model}: {usage}")

    # ctx is the JobContext from your entrypoint function
    async def log_usage():
        for usage in session.usage.model_usage:
            print(f"{usage.provider}/{usage.model}: {usage}")

    ctx.add_shutdown_callback(log_usage)

    await session.start(
        agent=GenericAgent(),
        room=ctx.room,
    )
    await ctx.connect()

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint)) # agent_name="<YOUR NAME>"