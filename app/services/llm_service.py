from langchain_anthropic import ChatAnthropic

from app.config import settings


def get_chat_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        temperature=0.7,
        max_tokens=1024,
    )
