"""LLM Provider Interface for Memory Core v2.

Memory Core v2 is framework-agnostic. It defines the interface
for proposing facts, and the host application provides the LLM implementation.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LLMProvider(ABC):
    """Abstract interface for LLM calls during consolidation."""

    @abstractmethod
    def generate_proposals(
        self,
        system_prompt: str,
        episodes_json: str,
        context_json: str,
    ) -> List[Dict[str, Any]]:
        """
        Send the prompt to the LLM and return a list of parsed JSON proposals.
        Must enforce JSON output natively or via retry logic.
        
        Args:
            system_prompt: The instruction prompt.
            episodes_json: JSON string of episodes to digest.
            context_json: JSON string of relevant existing facts.
            
        Returns:
            A list of dictionaries representing proposals (type, content, lane, etc.).
        """
        pass


class MockLLM(LLMProvider):
    """A deterministic mock LLM for testing. Ignores the prompt and yields fixed proposals."""

    def __init__(self, predefined_proposals: Optional[List[Dict[str, Any]]] = None) -> None:
        self.proposals = predefined_proposals or []
        self.call_count = 0
        self.last_episodes_json: Optional[str] = None
        self.last_context_json: Optional[str] = None

    def generate_proposals(
        self,
        system_prompt: str,
        episodes_json: str,
        context_json: str,
    ) -> List[Dict[str, Any]]:
        self.call_count += 1
        self.last_episodes_json = episodes_json
        self.last_context_json = context_json
        return self.proposals
