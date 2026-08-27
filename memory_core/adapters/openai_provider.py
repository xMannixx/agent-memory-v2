"""OpenAI concrete adapter for Memory Core v2."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from ..llm import LLMProvider

logger = logging.getLogger("memory_core.adapters.openai")


class OpenAILlm(LLMProvider):
    """Concrete LLM Provider using the official OpenAI client."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4-turbo",
        max_retries: int = 2
    ) -> None:
        try:
            import openai
        except ImportError:
            raise ImportError(
                "The 'openai' package is required to use OpenAILlm. "
                "Install it with: pip install openai"
            )
            
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model
        self.max_retries = max_retries

    def generate_proposals(
        self,
        system_prompt: str,
        episodes_json: str,
        context_json: str,
    ) -> List[Dict[str, Any]]:
        """Call OpenAI with JSON mode enabled to digest episodes."""
        
        user_prompt = (
            f"Context (Existing Facts):\n{context_json}\n\n"
            f"New Episodes to Digest:\n{episodes_json}\n\n"
            "Return a JSON object with a single key 'proposals' containing "
            "a list of your proposal objects."
        )
        
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                
                raw = response.choices[0].message.content
                if not raw:
                    logger.warning("Empty response from OpenAI (attempt %d)", attempt)
                    continue
                    
                parsed = json.loads(raw)

                # Handle both {"proposals": [...]} and bare [...] formats.
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    proposals = parsed.get("proposals", [])
                    if isinstance(proposals, list):
                        return proposals
                    logger.warning(
                        "OpenAI response 'proposals' key is not a list: %s",
                        type(proposals).__name__,
                    )
                else:
                    logger.warning(
                        "OpenAI response is neither list nor dict: %s",
                        type(parsed).__name__,
                    )
                    
            except json.JSONDecodeError as e:
                logger.warning("JSON parse error (attempt %d): %s", attempt, e)
                if attempt == self.max_retries:
                    raise RuntimeError(f"OpenAI adapter: invalid JSON after {self.max_retries} retries: {e}")
            except Exception as e:
                if attempt == self.max_retries:
                    raise RuntimeError(f"OpenAI adapter failed after {self.max_retries} retries: {e}")
                logger.warning("OpenAI call failed (attempt %d): %s", attempt, e)
                continue
                
        return []
