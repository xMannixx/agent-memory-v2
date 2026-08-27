"""Memory Core v2 — local-first long-term memory for LLM agents."""

__version__ = "2.0.0"

from .config import Config, load_config
from .router import StorageRouter
from .consolidator import Consolidator
from .facts import FactStore, AUTHORITY_POLICY
from .episodes import EpisodeStore
from .narratives import NarrativeStore
from .queue import ProposalQueue
from .audit import AuditLog
from .gates import GatePipeline, PipelineContext, GateResult
from .api import memory_context, recall, add_episode, add_conversation_turn, get_facts, get_stats
from .ingester import EpisodeIngester
from .llm import LLMProvider
from .models import Episode, Fact, Narrative, Proposal, Lesson, Entity

__all__ = [
    "__version__",
    "Config",
    "load_config",
    "StorageRouter",
    "Consolidator",
    "FactStore",
    "AUTHORITY_POLICY",
    "EpisodeStore",
    "NarrativeStore",
    "ProposalQueue",
    "AuditLog",
    "GatePipeline",
    "PipelineContext",
    "GateResult",
    "memory_context",
    "recall",
    "add_episode",
    "add_conversation_turn",
    "get_facts",
    "get_stats",
    "EpisodeIngester",
    "LLMProvider",
    "Episode",
    "Fact",
    "Narrative",
    "Proposal",
    "Lesson",
    "Entity",
]
