import asyncio

from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    function_tool,
    cli,
    room_io
)
from livekit.plugins import cartesia, openai, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv()

from llama_index.core import VectorStoreIndex, Settings, SimpleDirectoryReader, StorageContext
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from qdrant_client import QdrantClient, AsyncQdrantClient

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


# used only once to ingest the data
def ingest_knowledge():
    documents = (SimpleDirectoryReader(input_files=[
        "/Users/pavanmantha/Pavans/Workshops/s2s_agents/data/MF_Base_OC.md"])
                 .load_data(show_progress=True))
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    Settings.chunk_size = 512
    VectorStoreIndex.from_documents(
        documents,
        storage_context=storage_context,
        show_progress=True,
    )


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


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    agent = Agent(
        instructions=(
            "You are a mortgage voice assistant created by LiveKit. Your interface "
            "with users will be voice. You should use short and concise "
            "responses, and avoiding usage of unpronouncable punctuation."
            "Always use your tools to get the realtime information."
            "If you dont find any information politely respond the same to user."
            "Never answer anything other than mortgage subject and reject politely."
        ),
        stt=cartesia.STT(),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=cartesia.TTS(model="sonic-3", voice="630ed21c-2c5c-41cf-9d82-10a7fd668370"), # voice-id: 9626c31c-bec5-4cca-baa8-f8ba9e84c8bc, f786b574-daa5-4673-aa0c-cbe3e8534c02, 630ed21c-2c5c-41cf-9d82-10a7fd668370
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
        tools=[query_info],
    )

    session = AgentSession()  # Semantic turn detection
    await session.start(agent=agent, room=ctx.room, room_options=room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=noise_cancellation.BVC()
        )
    ))

    await session.say("Hello, how can i help you?", allow_interruptions=False)


# What does FHA Section 223(f) of the Housing Act provide for?
# What two criteria must be met for an exchange of related Classes within a Series to be permitted?
if __name__ == "__main__":
    #cli.run_app(server)
    ingest_knowledge()
    # asyncio.run(query_info("What was 30-day Average SOFR referred to in Series issued before July 2023?"))
