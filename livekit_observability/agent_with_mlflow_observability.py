import os
import logging

from livekit.agents import JobContext, JobProcess, WorkerOptions, cli, function_tool
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.telemetry import set_tracer_provider
from livekit.plugins import openai, silero, cartesia

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME

from dotenv import load_dotenv, find_dotenv

from llama_index.core import VectorStoreIndex, Settings, SimpleDirectoryReader, StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from qdrant_client import QdrantClient, AsyncQdrantClient

load_dotenv(find_dotenv())

# configs
Settings.embed_model = OllamaEmbedding(model_name="embeddinggemma:latest")
Settings.llm = Ollama(model="gemma3:latest")

# creates a persistant index to disk
client = QdrantClient(url="http://localhost:6333", api_key="th3s3cr3tk3y")
aclient = AsyncQdrantClient(url="http://localhost:6333", api_key="th3s3cr3tk3y")

# create our vector store with hybrid indexing enabled
vector_store = QdrantVectorStore(
    "mortgage",
    client=client,
    aclient=aclient
)

# create the index reference to vector store
index = VectorStoreIndex.from_vector_store(vector_store=vector_store)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")

@function_tool()
async def query_info(query: str) -> str:
    """Get more information about a specific topic"""
    print(f"query: {query}")
    retriever = index.as_retriever(similarity_top_k=20)
    nodes_with_scores = retriever.retrieve(query)
    context = ""
    for node in nodes_with_scores:
        print(f"Query result: {node.text}")
        context = context + node.text + ". \n"
    return context


def configure_mlflow_tracing():
    """Configure OpenTelemetry to send traces to MLflow."""
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        logger.warning("OTEL_EXPORTER_OTLP_ENDPOINT not set, tracing disabled")
        return None

    service_name = os.getenv("OTEL_SERVICE_NAME", "livekit-voice-agent")
    resource = Resource.create({SERVICE_NAME: service_name})

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    # Set both global and LiveKit tracer provider
    trace.set_tracer_provider(provider)
    set_tracer_provider(provider)

    logger.info("MLflow tracing configured successfully!")
    return provider


async def entrypoint(ctx: JobContext) -> None:
    """Main entrypoint for the agent."""
    logger.info(f"Agent starting for room: {ctx.room.name}")

    # Connect to the room
    await ctx.connect()

    # Create the voice agent with all components
    agent = Agent(
        instructions=(
            "You are a helpful mortgage voice assistant. Your interface "
            "with users will be voice. You should use short and concise "
            "responses, and avoiding usage of unpronouncable punctuation."
            "Always use your tools to get the realtime information."
            "If you dont find any information politely respond the same to user."
            "Never answer anything other than mortgage subject and reject politely."
            "Keep your responses concise and conversational since you're speaking out loud."
            "Be friendly and helpful."
        ),
        stt=cartesia.STT(), # Speech-to-Text
        llm=openai.LLM(model="gpt-4o-mini"), # Language Model
        # voice-id: 9626c31c-bec5-4cca-baa8-f8ba9e84c8bc, f786b574-daa5-4673-aa0c-cbe3e8534c02, 630ed21c-2c5c-41cf-9d82-10a7fd668370
        tts=cartesia.TTS(model="sonic-3", voice="630ed21c-2c5c-41cf-9d82-10a7fd668370"), # Text-to-Speech
        vad=silero.VAD.load(),
        tools=[query_info]
    )

    # Create and start the agent session
    session = AgentSession()
    await session.start(agent, room=ctx.room)

    logger.info("Agent session started! Ready for conversation.")


def prewarm(proc: JobProcess) -> None:
    """Prewarm function to load models before handling requests."""
    # Configure tracing before anything else
    configure_mlflow_tracing()

    # Preload Silero VAD model for faster startup
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("Prewarmed VAD model")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        )
    )