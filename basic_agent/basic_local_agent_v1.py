import asyncio
import logging
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv, find_dotenv
from fastembed import TextEmbedding
from livekit import agents
from livekit.agents import Agent, AgentSession, ChatContext, ChatMessage, TurnHandlingOptions, llm, room_io
from livekit.plugins import cartesia, openai
from qdrant_edge import (
    Distance,
    EdgeConfig,
    EdgeShard,
    EdgeVectorParams,
    Point,
    Query,
    QueryRequest,
    UpdateOperation,
)

load_dotenv(find_dotenv())

logger = logging.getLogger("voice-agent")


class ConversationMemory:
    VECTOR_NAME = "conversation"

    def __init__(self, shard_dir="./qdrant-edge-memory", model_name="BAAI/bge-small-en-v1.5", dimension=384):
        self.shard_dir = Path(shard_dir)
        self.embedder = TextEmbedding(model_name=model_name, cache_dir=str(self.shard_dir.parent / "fastembed-models"))
        self.lock = threading.Lock()
        self.shard = self._open(dimension)

    def _open(self, dimension):
        if (self.shard_dir / "edge_config.json").exists():
            return EdgeShard.load(str(self.shard_dir))
        self.shard_dir.mkdir(parents=True, exist_ok=True)
        config = EdgeConfig(
            vectors={self.VECTOR_NAME: EdgeVectorParams(size=dimension, distance=Distance.Cosine)}
        )
        return EdgeShard.create(str(self.shard_dir), config)

    def _embed(self, text):
        return list(self.embedder.embed([text]))[0].tolist()

    def save(self, question, answer):
        vector = self._embed(f"User: {question}\nAssistant: {answer}")
        point = Point(
            id=str(uuid.uuid4()),
            vector={self.VECTOR_NAME: vector},
            payload={
                "date": datetime.now().astimezone().isoformat(timespec="seconds"),
                "question": question,
                "answer": answer,
            },
        )
        with self.lock:
            self.shard.update(UpdateOperation.upsert_points([point]))

    def search(self, query, limit=3):
        vector = self._embed(query)
        with self.lock:
            hits = self.shard.query(
                QueryRequest(
                    query=Query.Nearest(vector, using=self.VECTOR_NAME),
                    limit=limit,
                    with_vector=False,
                    with_payload=True,
                )
            )
        return [hit.payload for hit in hits]

    def close(self):
        with self.lock:
            self.shard.optimize()
            self.shard.close()


class GeneralAssistant(Agent):
    def __init__(self, memory):
        super().__init__(
            instructions=("You are a conversational agent you caht with user on any topic that user initiate with you."
                          "You dont have any boundaries or restrictions on the topics that you can speak. "
                          "but the conversation should be very polite and the topic oriented and topic bounded"),
        )
        self.memory = memory

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        question = MemoryRecorder.text_of(new_message)
        if not question:
            return
        memories = await asyncio.to_thread(self.memory.search, question)
        logger.info("memory search returned %d item(s)", len(memories))
        if not memories:
            return
        notes = "\n".join(
            f"- [{m['date']}] The user said: \"{m['question']}\" You replied: \"{m['answer']}\""
            for m in memories
        )
        turn_ctx.add_message(
            role="system",
            content=(
                "Notes from earlier conversations with this user. Use them only as background facts. "
                "Never repeat or continue the earlier replies. Answer the user's new message directly.\n\n"
                f"{notes}"
            ),
        )

    async def llm_node(self, chat_ctx, tools, model_settings):
        logger.info("llm request sent with %d message(s)", len(chat_ctx.items))
        characters = 0
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if isinstance(chunk, llm.ChatChunk) and chunk.delta and chunk.delta.content:
                characters += len(chunk.delta.content)
            yield chunk
        logger.info("llm response finished with %d character(s)", characters)


class MemoryRecorder:
    def __init__(self, session, memory):
        self.memory = memory
        self.pending_question = None
        self.tasks = set()
        session.on("conversation_item_added", self._on_item)

    @staticmethod
    def text_of(message):
        text = getattr(message, "text_content", None)
        text = text() if callable(text) else text
        return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()

    def _on_item(self, event):
        item = event.item
        role = getattr(item, "role", None)
        text = self.text_of(item)
        if not text:
            return
        if role == "user":
            self.pending_question = text
        elif role == "assistant" and self.pending_question:
            question, self.pending_question = self.pending_question, None
            print(f"\nUser: {question}\nAssistant: {text}\n")
            task = asyncio.create_task(asyncio.to_thread(self.memory.save, question, text))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)


async def entrypoint(ctx: agents.JobContext):
    memory = await asyncio.to_thread(ConversationMemory)

    session = AgentSession(
        stt=cartesia.STT(),
        llm=openai.LLM.with_ollama(model="lfm3-omni:latest", base_url="http://localhost:11434/v1"),
        turn_handling=TurnHandlingOptions(preemptive_generation={"enabled": False}),
    )
    session.output.set_audio_enabled(False)
    recorder = MemoryRecorder(session, memory)

    async def shutdown():
        await asyncio.gather(*recorder.tasks, return_exceptions=True)
        memory.close()

    ctx.add_shutdown_callback(shutdown)

    await session.start(
        room=ctx.room,
        agent=GeneralAssistant(memory),
        room_options=room_io.RoomOptions(audio_output=False),
    )


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint, agent_name="MortgageAgent"))