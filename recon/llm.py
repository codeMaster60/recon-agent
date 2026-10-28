"""Minimal OpenAI-compatible chat client (Groq by default). Standard library only.

Configure with environment variables:
    RECON_LLM_API_KEY   (or GROQ_API_KEY / OPENAI_API_KEY)
    RECON_LLM_BASE_URL  default https://api.groq.com/openai/v1
    RECON_LLM_MODEL     default llama-3.3-70b-versatile

No key set -> get_client() returns None and the pipeline runs on rules alone.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Protocol


class LLMClient(Protocol):
    model: str

    def chat(self, system: str, user: str, json_mode: bool = False) -> str: ...


class LLMError(RuntimeError):
    pass


class OpenAICompatClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 45.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, system: str, user: str, json_mode: bool = False) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM call failed: {exc}") from exc
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected LLM response: {payload}") from exc


def get_client() -> OpenAICompatClient | None:
    key = os.getenv("RECON_LLM_API_KEY") or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    default_base = "https://api.openai.com/v1" if (os.getenv("OPENAI_API_KEY") and not os.getenv("GROQ_API_KEY")
                                                  and not os.getenv("RECON_LLM_API_KEY")) else "https://api.groq.com/openai/v1"
    default_model = "gpt-4o-mini" if "openai.com" in default_base else "llama-3.3-70b-versatile"
    return OpenAICompatClient(
        api_key=key,
        base_url=os.getenv("RECON_LLM_BASE_URL", default_base),
        model=os.getenv("RECON_LLM_MODEL", default_model),
    )


def parse_json_object(text: str) -> dict:
    """Pull the first JSON object out of a model reply, tolerating code fences and chatter."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise LLMError(f"No JSON object in reply: {text[:200]}")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise LLMError("Reply JSON is not an object")
    return value
