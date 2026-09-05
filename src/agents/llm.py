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


async def complete(system: str, prompt: str, max_tokens: int = 4000) -> LLMResult:
    if not configured():
        return LLMResult(text=_mock_response(prompt), input_tokens=0, output_tokens=0, mock=True)
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    resp = await client.messages.create(
        model=settings.default_llm_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return LLMResult(
        text=text,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a model response (handles ```json fences)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start != -1:
        candidates.append(text[start : text.rfind("}") + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
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
