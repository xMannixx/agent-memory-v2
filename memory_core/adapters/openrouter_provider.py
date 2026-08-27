"""OpenRouter adapter for Memory Core v2.

Uses the OpenRouter HTTP API (stdlib ``urllib`` only, no external dependencies).
OpenRouter provides access to hundreds of models (Llama, Mistral, Qwen,
DeepSeek, etc.) through a single API compatible with the OpenAI format.

Usage::

    from memory_core.adapters.openrouter_provider import OpenRouterLlm

    # Requires OPENROUTER_API_KEY env var or explicit api_key
    llm = OpenRouterLlm(model="meta-llama/llama-3.1-70b-instruct", api_key="...")

    # Or with a free model
    llm = OpenRouterLlm(model="meta-llama/llama-3.3-70b-instruct:free")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..llm import LLMProvider

logger = logging.getLogger("memory_core.adapters.openrouter")

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterLlm(LLMProvider):
    """Concrete LLM provider using OpenRouter.

    Parameters
    ----------
    model : str
        The OpenRouter model identifier
        (e.g. ``"meta-llama/llama-3.1-70b-instruct"``).
    api_key : str or None
        API key. Falls back to ``OPENROUTER_API_KEY`` env var.
    max_retries : int
        Max retries on failure.
    temperature : float
        Sampling temperature. Default 0.2 for deterministic output.
    timeout : int
        HTTP request timeout in seconds. Default 120.
    """

    def __init__(
        self,
        model: str = "meta-llama/llama-3.1-70b-instruct",
        api_key: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.2,
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key required. Pass api_key= or set "
                "OPENROUTER_API_KEY env var."
            )
        self.max_retries = max_retries
        self.temperature = temperature
        self.timeout = timeout

    def generate_proposals(
        self,
        system_prompt: str,
        episodes_json: str,
        context_json: str,
    ) -> List[Dict[str, Any]]:
        """Call OpenRouter with JSON output to digest episodes."""

        user_prompt = (
            f"Context (Existing Facts):\n{context_json}\n\n"
            f"New Episodes to Digest:\n{episodes_json}\n\n"
            "Return a JSON object with a single key 'proposals' containing "
            "a list of your proposal objects. Output ONLY valid JSON."
        )

        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                result = self._call_openrouter(payload)
                return self._parse_response(result)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "OpenRouter JSON parse error (attempt %d/%d): %s",
                    attempt + 1, self.max_retries + 1, e,
                )
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"OpenRouter adapter: invalid JSON after "
                        f"{self.max_retries + 1} attempts: {e}"
                    )
            except Exception as e:
                logger.warning(
                    "OpenRouter call failed (attempt %d/%d): %s",
                    attempt + 1, self.max_retries + 1, e,
                )
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"OpenRouter adapter failed after "
                        f"{self.max_retries + 1} attempts: {e}"
                    )

        return []

    def _call_openrouter(self, payload: bytes) -> Dict[str, Any]:
        """Make a single HTTP call to OpenRouter /chat/completions."""
        url = f"{_BASE_URL}/chat/completions"
        req = Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = "(no body)"
            raise RuntimeError(
                f"OpenRouter HTTP {e.code}: {body}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"OpenRouter connection failed: {e.reason}"
            ) from e

    def _parse_response(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse OpenRouter chat response into a list of proposals."""
        choices = result.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter returned empty choices")

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise ValueError("Empty content from OpenRouter")

        parsed = json.loads(content)

        # Handle both {"proposals": [...]} and bare [...] formats.
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            proposals = parsed.get("proposals", [])
            if isinstance(proposals, list):
                return proposals
            raise ValueError(
                f"OpenRouter 'proposals' key is not a list: "
                f"{type(proposals).__name__}"
            )
        raise ValueError(
            f"OpenRouter response is neither list nor dict: "
            f"{type(parsed).__name__}"
        )

    def __repr__(self) -> str:
        return (
            f"OpenRouterLlm(model={self.model!r})"
        )