"""
LLM — OpenAI gpt-4o-mini với conversation history làm context.

Service bắt buộc có `OPENAI_API_KEY` trong env. Không fallback mock.
"""
import os
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant for the Day 12 Lab demo. "
    "Trả lời ngắn gọn, bằng tiếng Việt nếu user hỏi bằng tiếng Việt."
)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy singleton client — raise rõ ràng nếu thiếu env."""
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required. Set it in Railway variables or .env."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def ask(question: str, history: list[dict] | None = None) -> str:
    """
    Gọi OpenAI chat completions.

    - `question`: câu hỏi user vừa gửi
    - `history`: list[{role, content, ts}] — turn trước, dùng làm context multi-turn

    Return: string trả lời từ gpt-4o-mini.
    """
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        for h in history:
            role = h.get("role")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    resp = _get_client().chat.completions.create(
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        messages=messages,
        max_tokens=int(os.getenv("MAX_TOKENS", "500")),
        temperature=0.7,
    )
    return (resp.choices[0].message.content or "").strip()
