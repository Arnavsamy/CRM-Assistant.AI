from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Groq is the default inexpensive inference provider. Gemini is optional.
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    LLM_MODEL: Optional[str] = None
    LLM_MAX_TOKENS: int = 1000

    # PostgreSQL stores application data. Chroma stores RAG vectors locally.
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/outreach_db"
    CHROMA_PERSIST_DIRECTORY: str = str(Path(__file__).resolve().parent / "chroma_data")
    USE_MOCK_DB: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    MCP_PORT: int = 8001
    # Keep free hosted deployments responsive; local development can raise it.
    DISCOVERY_COMPANY_LIMIT: int = 2

    # Google OAuth is used for user-authorized Gmail/Calendar actions.
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://127.0.0.1:8000/api/integrations/google/callback"
    FRONTEND_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
