from dotenv import load_dotenv, find_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    ChatContext,
    ChatMessage,
    JobContext,
    cli,
    room_io,
)
from livekit.plugins import cartesia, openai, noise_cancellation, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from llama_index.core import VectorStoreIndex, Settings
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from qdrant_client import QdrantClient, AsyncQdrantClient
from llama_index.vector_stores.qdrant import QdrantVectorStore

load_dotenv(find_dotenv())

# configs
Settings.embed_model = OllamaEmbedding(model_name="embeddinggemma:latest")
Settings.llm = Ollama(model="gemma3:latest")

# persistent index on disk (Qdrant)
client = QdrantClient(url="http://localhost:6333", api_key="th3s3cr3tk3y")
aclient = AsyncQdrantClient(url="http://localhost:6333", api_key="th3s3cr3tk3y")

vector_store = QdrantVectorStore(
    "mortgage",
    client=client,
    aclient=aclient,
)

index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
retriever = index.as_retriever(similarity_top_k=20)


async def retrieve_context(query: str) -> str:
    """Runs a similarity search against the mortgage index and returns
    concatenated node text, or an empty string if nothing is found."""
    nodes_with_scores = retriever.retrieve(query)
    context = ""
    for node in nodes_with_scores:
        context += node.text + ". \n"
    return context


class MortgageRAGAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions=(
                "You are a mortgage voice assistant created by LiveKit. Your interface "
                "with users will be voice. You should use short and concise "
                "responses, and avoid usage of unpronounceable punctuation. "
                "You will be given retrieved context relevant to the user's question "
                "before you respond \u2014 base your answer on that context. "
                "If the retrieved context does not contain the answer, politely tell "
                "the user you don't have that information. "
                "Never answer anything other than mortgage subject and reject politely."
            ),
            stt=cartesia.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),
            tts=cartesia.TTS(
                model="sonic-3",
                voice="630ed21c-2c5c-41cf-9d82-10a7fd668370",
            ),
            vad=silero.VAD.load(),
            turn_detection=MultilingualModel(),
        )

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        # Runs on every user turn, before the LLM generates a reply.
        query = new_message.text_content
        if not query:
            return

        retrieved = await retrieve_context(query)

        if retrieved:
            turn_ctx.add_message(
                role="assistant",
                content=(
                    "Relevant mortgage reference material for the user's last "
                    f"question:\n{retrieved}"
                ),
            )
        else:
            turn_ctx.add_message(
                role="assistant",
                content=(
                    "No relevant mortgage reference material was found for the "
                    "user's last question."
                ),
            )

        # Persist so the injected context stays part of the running history
        # for this session. Remove this line if you'd rather scope the
        # injection to the current turn only (leaner context, no memory of
        # what was retrieved earlier).
        await self.update_chat_ctx(turn_ctx)


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    session = AgentSession()  # Semantic turn detection
    await session.start(
        agent=MortgageRAGAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC()
            )
        ),
    )

    await session.say("Hello, how can I help you?", allow_interruptions=False)


if __name__ == "__main__":
    cli.run_app(server)