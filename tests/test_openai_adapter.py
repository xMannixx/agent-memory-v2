"""Tests for the OpenAI Adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.adapters.openai_provider import OpenAILlm


def test_openai_missing_package(monkeypatch):
    # Hide openai from sys.modules to simulate missing package
    monkeypatch.setitem(sys.modules, "openai", None)
    
    with pytest.raises(ImportError, match="The 'openai' package is required"):
        OpenAILlm("fake_key")


def test_openai_generation(monkeypatch):
    mock_openai = MagicMock()
    monkeypatch.setitem(sys.modules, "openai", mock_openai)
    
    # Setup mock response
    mock_client = MagicMock()
    mock_openai.OpenAI.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"proposals": [{"type": "fact", "content": "Test"}]}'
    mock_client.chat.completions.create.return_value = mock_response
    
    llm = OpenAILlm("fake_key")
    proposals = llm.generate_proposals("sys", "episodes", "context")
    
    assert len(proposals) == 1
    assert proposals[0]["content"] == "Test"
    
    # Verify strict JSON mode was requested
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["model"] == "gpt-4-turbo"
