"""Thin Anthropic wrapper. Mock mode when no key is configured."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import anthropic

from src.config import settings


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    mock: bool = False


def configured() -> bool:
    return bool(settings.anthropic_api_key)


async def complete(
    system: str, prompt: str, max_tokens: int = 4000, web_searches: int = 0
) -> LLMResult:
    """One-shot completion. ``web_searches`` > 0 enables Anthropic's server-side web search
    tool (bounded by that many searches) so the model can ground itself in live results."""
    if not configured():
        return LLMResult(text=_mock_response(prompt), input_tokens=0, output_tokens=0, mock=True)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    kwargs: dict = {}
    if web_searches > 0:
        kwargs["tools"] = [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": web_searches}
        ]
    resp = await client.messages.create(
        model=settings.default_llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return LLMResult(
        text=text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


def extract_json(text: str) -> dict | None:
    """Pull the JSON object out of a model response (handles ```json fences and prose
    around it; with web search the answer is often the *last* object, after citations)."""
    fences = re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [m.group(1) for m in fences]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
        # Prose before the object may itself contain braces; retry from each later '{'.
        for m in re.finditer(r"\{", text[start + 1 : end], re.DOTALL):
            candidates.append(text[start + 1 + m.start() : end + 1])
    for c in candidates[:40]:
        try:
            out = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(out, dict):
            return out
    return None


def _mock_response(prompt: str) -> str:
    return json.dumps(
        {
            "summary": (
                "Mock run (no ANTHROPIC_API_KEY configured). Context received: "
                f"{len(prompt)} chars."
            ),
            "recommendations": [
                {
                    "title": "Configure ANTHROPIC_API_KEY to enable real agent runs",
                    "body": "Agents run in mock mode until an Anthropic key is set on the server.",
                    "kind": "task",
                    "impact": "high",
                    "effort": "low",
                }
            ],
        }
    )
