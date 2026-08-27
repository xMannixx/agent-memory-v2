"""Ollama adapter for Memory Core v2.

Uses the Ollama HTTP API (stdlib ``urllib`` only, no external dependencies).
Requires a running Ollama instance (default: ``http://localhost:11434``).

Usage::

    from memory_core.adapters.ollama_provider import OllamaLlm

    llm = OllamaLlm(model="llama3.1")
    # or with a custom host:
    llm = OllamaLlm(model="llama3.1", host="http://192.168.1.100:11434")
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..llm import LLMProvider

logger = logging.getLogger("memory_core.adapters.ollama")

_DEFAULT_HOST = "http://localhost:11434"


class OllamaLlm(LLMProvider):
    """Concrete LLM provider using a local Ollama instance.

    Parameters
    ----------
    model : str
        The Ollama model name (e.g. ``"llama3.1"``, ``"mistral"``, ``"qwen2.5"``).
    host : str
        The Ollama HTTP base URL. Default ``http://localhost:11434``.
    max_retries : int
        Max retries on failure.
    temperature : float
        Sampling temperature. Default 0.2 for deterministic output.
    timeout : int
        HTTP request timeout in seconds. Default 120 (LLM can be slow).
    """

    def __init__(
        self,
        model: str = "llama3.1",
        host: str = _DEFAULT_HOST,
        max_retries: int = 2,
        temperature: float = 0.2,
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.max_retries = max_retries
        self.temperature = temperature
        self.timeout = timeout

    def generate_proposals(
        self,
        system_prompt: str,
        episodes_json: str,
        context_json: str,
    ) -> List[Dict[str, Any]]:
        """Call Ollama with JSON output to digest episodes."""

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
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
            },
        }).encode("utf-8")

        for attempt in range(self.max_retries + 1):
            try:
                result = self._call_ollama(payload)
                return self._parse_response(result)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(
                    "Ollama JSON parse error (attempt %d/%d): %s",
                    attempt + 1, self.max_retries + 1, e,
                )
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"Ollama adapter: invalid JSON after "
                        f"{self.max_retries + 1} attempts: {e}"
                    )
            except Exception as e:
                logger.warning(
                    "Ollama call failed (attempt %d/%d): %s",
                    attempt + 1, self.max_retries + 1, e,
                )
                if attempt == self.max_retries:
                    raise RuntimeError(
                        f"Ollama adapter failed after "
                        f"{self.max_retries + 1} attempts: {e}"
                    )

        return []

    def _call_ollama(self, payload: bytes) -> Dict[str, Any]:
        """Make a single HTTP call to Ollama /api/chat."""
        url = f"{self.host}/api/chat"
        req = Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
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
                f"Ollama HTTP {e.code}: {body}"
            ) from e
        except URLError as e:
            raise RuntimeError(
                f"Ollama connection failed: {e.reason}. "
                f"Is Ollama running at {self.host}?"
            ) from e

    def _parse_response(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Ollama chat response into a list of proposals."""
        # Ollama returns {"message": {"content": "..."}, ...}
        message = result.get("message", {})
        content = message.get("content", "")
        if not content:
            raise ValueError("Empty content from Ollama")

        parsed = json.loads(content)

        # Handle both {"proposals": [...]} and bare [...] formats.
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            proposals = parsed.get("proposals", [])
            if isinstance(proposals, list):
                return proposals
            raise ValueError(
                f"Ollama 'proposals' key is not a list: "
                f"{type(proposals).__name__}"
            )
        raise ValueError(
            f"Ollama response is neither list nor dict: "
            f"{type(parsed).__name__}"
        )

    def __repr__(self) -> str:
        return (
            f"OllamaLlm(model={self.model!r}, "
            f"host={self.host!r})"
        )
