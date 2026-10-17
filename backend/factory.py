import logging
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from backend.config import settings

logger = logging.getLogger(__name__)


def get_chat_model(provider: Optional[str] = None, model: Optional[str] = None,
                   temperature: float = 0.0) -> BaseChatModel:
    """Create the configured low-cost chat model (Groq by default, Gemini optional)."""
    provider = (provider or settings.LLM_PROVIDER).lower()
    if provider == "groq":
        if not settings.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        from langchain_groq import ChatGroq
        return ChatGroq(
            api_key=settings.GROQ_API_KEY,
            model=model or settings.LLM_MODEL or "openai/gpt-oss-20b",
            temperature=temperature,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    if provider == "gemini":
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            google_api_key=settings.GEMINI_API_KEY,
            model=model or settings.LLM_MODEL or "gemini-2.0-flash",
            temperature=temperature,
            max_output_tokens=settings.LLM_MAX_TOKENS,
        )
    raise ValueError("LLM_PROVIDER must be 'groq' or 'gemini'")
