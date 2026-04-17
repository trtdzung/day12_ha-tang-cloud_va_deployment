"""
LLM dispatch — gọi OpenAI nếu `OPENAI_API_KEY` set, fallback mock.

Real LLM dùng conversation history làm context để multi-turn có ý nghĩa.
"""
import os
import logging

from .mock_llm import ask as _mock_ask

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a helpful AI assistant for the Day 12 Lab demo. "
    "Trả lời ngắn gọn, bằng tiếng Việt nếu user hỏi bằng tiếng Việt."
)


def ask(question: str, history: list[dict] | None = None) -> str:
    """
    Gọi LLM.

    - `question`: câu hỏi user vừa gửi
    - `history`: list[{role, content, ts}] — các turn trước trong session này.
      Mock bỏ qua. Real LLM dùng để giữ ngữ cảnh multi-turn.

    Return: string trả lời.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _mock_ask(question)

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai SDK not installed — falling back to mock")
        return _mock_ask(question)

    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        # Chỉ lấy role + content; bỏ timestamp
        for h in history:
            role = h.get("role")
            content = h.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            messages=messages,
            max_tokens=int(os.getenv("MAX_TOKENS", "500")),
            temperature=0.7,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("OpenAI call failed (%s) — falling back to mock", exc)
        return _mock_ask(question)
