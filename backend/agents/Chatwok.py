import asyncio
from collections import defaultdict
from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from backend.config import settings
from backend.Trace1 import RequestTrace

SYSTEM = """You are an AI outreach assistant. Help research prospects and draft concise,
truthful outreach. Never invent company facts; ask for missing details."""
_sessions: dict[str, list[BaseMessage]] = defaultdict(list)
_lock = asyncio.Lock()


class ChatState(TypedDict):
    trace: RequestTrace
    message: str
    session_id: str
    history: list[BaseMessage]
    prompt: list[BaseMessage]
    answer: str


async def _prompt(state: ChatState) -> dict:
    await state["trace"].publish("status", {"stage": "building_prompt"})
    return {"prompt": [SystemMessage(content=SYSTEM), *state["history"], HumanMessage(content=state["message"])]}


async def _generate(state: ChatState) -> dict:
    trace = state["trace"]
    await trace.publish("status", {"stage": "generating", "model": settings.groq_model})
    model = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, temperature=0.2, streaming=True)
    parts: list[str] = []
    async for chunk in model.astream(state["prompt"]):
        text = chunk.content if isinstance(chunk.content, str) else ""
        if text:
            parts.append(text)
            await trace.publish("token", {"text": text})
    return {"answer": "".join(parts)}


graph = StateGraph(ChatState)
graph.add_node("prompt", _prompt)
graph.add_node("generate", _generate)
graph.add_edge(START, "prompt")
graph.add_edge("prompt", "generate")
graph.add_edge("generate", END)
chat_graph = graph.compile()


async def get(session_id: str, message: str, trace: RequestTrace) -> str:
    """Async graph entry point used by the SSE GET endpoint."""
    async with _lock:
        history = list(_sessions[session_id])
    result = await chat_graph.ainvoke({"trace": trace, "message": message, "session_id": session_id, "history": history})
    async with _lock:
        _sessions[session_id].extend([HumanMessage(content=message), AIMessage(content=result["answer"])])
        _sessions[session_id] = _sessions[session_id][-settings.max_history_messages:]
    return result["answer"]
