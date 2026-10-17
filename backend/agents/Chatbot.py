"""Standalone Groq FastAPI chatbot.

Install in the SAME virtual environment used by Uvicorn:
    pip install fastapi "uvicorn[standard]" groq python-dotenv

Create a .env file in the project root:
    GROQ_API_KEY=your_groq_api_key
    GROQ_MODEL=llama-3.3-70b-versatile

Run from the project root:
    uvicorn backend.agents.Chatbot:app --reload
Open Swagger: http://127.0.0.1:8000/docs
"""

import logging
import os
import uuid
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from groq import AsyncGroq
from pydantic import BaseModel, Field

# Load project-root .env before reading GROQ_API_KEY.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(override=False)  # Also supports running Uvicorn from another folder.

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("groq_chatbot")

app = FastAPI(title="Groq Company Chatbot")
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
MAX_HISTORY_MESSAGES = 12
SESSIONS: dict[str, list[dict[str, str]]] = defaultdict(list)

SYSTEM_PROMPT = (
    "You are a concise AI and company-information assistant. Answer general questions about "
    "companies, founders, CEOs, services, and AI using conversation context. Do not invent facts; "
    "say when information may be outdated or unknown. Keep answers under 120 words."
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = Field(None, description="Reuse this ID for follow-up questions")
    reset: bool = Field(False, description="Clear this session before sending the message")


class ChatResponse(BaseModel):
    session_id: str
    answer: str


def get_groq_client() -> AsyncGroq:
    """Create the client only after .env has been loaded and the key is validated."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is missing. Add it to the project-root .env file and restart Uvicorn.",
        )
    return AsyncGroq(api_key=api_key)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Start a chat or send a follow-up using the returned session_id."""
    session_id = request.session_id or str(uuid.uuid4())
    if request.reset:
        SESSIONS[session_id] = []

    user_message = request.message.strip()
    history = SESSIONS[session_id]
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]

    client = get_groq_client()
    try:
        completion = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.2,
            max_tokens=220,
        )
        if not completion.choices or not completion.choices[0].message.content:
            raise RuntimeError("Groq returned an empty response.")
        answer = completion.choices[0].message.content.strip()
    except HTTPException:
        raise
    except Exception as exc:
        # logger.exception prints the complete real error and traceback in the VS Code terminal.
        logger.exception("Groq request failed (model=%s): %s", MODEL, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Groq request failed: {type(exc).__name__}. Check the VS Code terminal for the full traceback.",
        ) from exc
    finally:
        await client.close()

    history.extend([
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": answer},
    ])
    SESSIONS[session_id] = history[-MAX_HISTORY_MESSAGES:]
    return ChatResponse(session_id=session_id, answer=answer)