from openai import AsyncOpenAI

from app.config import settings


def get_llm_client() -> AsyncOpenAI:
    """Return a configured AsyncOpenAI client pointing at the Ollama endpoint."""
    return AsyncOpenAI(
        base_url=settings.OLLAMA_BASE_URL,
        api_key="ollama",
    )
