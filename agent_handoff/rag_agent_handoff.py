import logging
from datetime import datetime

from dotenv import load_dotenv, find_dotenv

logger = logging.getLogger("rag-report-handoff")

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    ChatContext,
    JobContext,
    RunContext,
    cli,
    function_tool,
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

client = QdrantClient(url="http://localhost:6333", api_key="th3s3cr3tk3y")
aclient = AsyncQdrantClient(url="http://localhost:6333", api_key="th3s3cr3tk3y")

vector_store = QdrantVectorStore("mortgage", client=client, aclient=aclient)
index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
retriever = index.as_retriever(similarity_top_k=20)


async def retrieve_context(query: str) -> str:
    nodes_with_scores = retriever.retrieve(query)
    context = ""
    for node in nodes_with_scores:
        context += node.text + ". \n"
    return context


class RetrievalAgent(Agent):
    """Agent 1: gathers information from the mortgage knowledge base and
    hands off to the ReportAgent once the user has what they need and
    wants it written up."""

    def __init__(self, chat_ctx: ChatContext | None = None):
        super().__init__(
            instructions=(
                "You are a mortgage research assistant. Your job is to help the "
                "user look up mortgage-related information using your retrieval "
                "tool. Keep responses short and conversational, since this is a "
                "voice interface. "
                "Once the user has gathered enough information and asks for a "
                "written report, a summary document, or says they're done "
                "researching, call transfer_to_report_writer."
            ),
            chat_ctx=chat_ctx,
            stt=cartesia.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),
            tts=cartesia.TTS(
                model="sonic-3",
                voice="630ed21c-2c5c-41cf-9d82-10a7fd668370",
            ),
            vad=silero.VAD.load(),
            turn_detection=MultilingualModel(),
        )

    async def on_enter(self) -> None:
        await self.session.generate_reply(
            instructions="Greet the user and ask what mortgage topic they'd like to research."
        )

    @function_tool()
    async def retrieve_mortgage_info(self, context: RunContext, query: str) -> str:
        """Use this tool to look up mortgage-related information from the
        knowledge base. Call it whenever the user asks a factual mortgage
        question."""
        result = await retrieve_context(query)
        return result if result else "No relevant information was found."

    @function_tool()
    async def transfer_to_report_writer(self, context: RunContext):
        """Hand off to the report-writing agent once the user wants a
        formatted written report of what's been discussed."""
        logger.info("transfer_to_report_writer called; handing off to ReportAgent")
        await self.session.generate_reply(
            instructions="Let the user know you're now preparing their written report."
        )
        # Carry the conversation history forward, minus this agent's own
        # instructions, so the report writer sees what was researched.
        return (
            ReportAgent(chat_ctx=self.chat_ctx.copy(exclude_instructions=True)),
            "Transferring to report writer",
        )


class ReportAgent(Agent):
    """Agent 2: takes the prior conversation/research and produces a
    formatted, NYT-style written report. No retrieval tools of its own \u2014
    it works purely from the handed-off chat context."""

    def __init__(self, chat_ctx: ChatContext | None = None):
        super().__init__(
            instructions=(
                "You are a report-writing specialist. You will be given the prior "
                "conversation, including retrieved mortgage information. Your job "
                "is to compose a single, well-structured written report in "
                "New York Times article style:\n"
                "1. HEADLINE \u2014 a concise, informative title in title case.\n"
                "2. DATELINE \u2014 today's date and 'MORTGAGE DESK' as the byline.\n"
                "3. LEDE \u2014 a one-paragraph summary answering who/what/why it matters.\n"
                "4. BODY \u2014 two to four short paragraphs expanding on the details, "
                "grounded strictly in the retrieved information from the prior "
                "conversation. Do not invent facts not present in that context.\n"
                "5. CLOSING \u2014 one sentence noting any open questions or caveats.\n"
                "Since this will be read aloud, keep sentences short and avoid "
                "unpronounceable punctuation. Present the report as plain narrated "
                "text, not markdown."
            ),
            chat_ctx=chat_ctx,
            # Without its own models, this agent would have nothing to speak
            # the report with once it becomes active \u2014 give it the same
            # voice pipeline as RetrievalAgent so the handoff actually reads
            # the report aloud instead of only generating silent text.
            stt=cartesia.STT(),
            llm=openai.LLM(model="gpt-4o-mini"),
            tts=cartesia.TTS(
                model="sonic-3",
                voice="630ed21c-2c5c-41cf-9d82-10a7fd668370",
            ),
            vad=silero.VAD.load(),
            turn_detection=MultilingualModel(),
        )

    async def on_enter(self) -> None:
        logger.info("ReportAgent.on_enter reached; composing report")
        today = datetime.now().strftime("%B %d, %Y")
        await self.session.generate_reply(
            instructions=(
                f"Today's date is {today}. Compose and deliver the full report now, "
                "following the HEADLINE / DATELINE / LEDE / BODY / CLOSING structure "
                "described in your instructions, based on the prior conversation."
            )
        )


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    session = AgentSession()
    await session.start(
        agent=RetrievalAgent(),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC()
            )
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)