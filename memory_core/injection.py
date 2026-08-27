"""Injection formatting for Memory Core v2.

Generates the `# Memory Context` block for LLM system prompts.
"""

from __future__ import annotations

from typing import List

from .config import Config
from .facts import FactStore
from .narratives import NarrativeStore


def get_injection_block(
    namespace: str,
    narrative_store: NarrativeStore,
    fact_store: FactStore,
    config: Config,
) -> str:
    """Generate the `# Memory Context` block, capped by length."""
    limit = config.narrative.max_chars
    
    narrative = narrative_store.get_latest(namespace)
    nar_text = narrative.content if narrative else "No background available yet."
    
    # We fetch a reasonable amount of top facts. In B4, we just fetch recent active facts.
    # A full host implementation would filter by semantic relevance, but the core provides the recent ones.
    facts = fact_store.list_facts(namespace, limit=50)
    fact_lines = [f"- {f.content}" for f in facts]
    
    header = "# Memory Context\n"
    
    # Build from bottom up to see what fits
    # 1. Header + Narrative
    base_text = f"{header}{nar_text}\n\n"
    
    if len(base_text) > limit:
        # We must truncate the narrative itself
        allowed = limit - len(header) - 3  # for "..."
        if allowed <= 0:
            return ""
        return f"{header}{nar_text[:allowed]}..."
        
    # 2. Add facts until we hit the limit
    final_lines = [base_text.strip()]
    current_len = len(base_text)
    
    if fact_lines:
        final_lines.append("\nRelevant Facts:")
        current_len += 16
        
        for line in fact_lines:
            # +1 for newline
            if current_len + len(line) + 1 > limit:
                break
            final_lines.append(line)
            current_len += len(line) + 1
            
    return "\n".join(final_lines)
