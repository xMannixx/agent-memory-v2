"""Consolidator Run Loop for Memory Core v2.

The background worker that digests unconsumed episodes into structured facts.
Enforces INV-3 (asynchronous, decoupled from user latency).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from .audit import AuditLog
from .config import Config
from .episodes import EpisodeStore
from .facts import FactStore
from .gates import GatePipeline, PipelineContext
from .llm import LLMProvider
from .narratives import NarrativeStore
from .queue import ProposalQueue
from .router import StorageRouter


logger = logging.getLogger("memory_core.consolidator")


_SYSTEM_PROMPT = """You are the Memory Consolidator.
Your job is to read new episodes and existing memory facts, and output JSON proposals to update the memory.
Proposals must be a JSON array of objects.

Types of proposals:
1. {"type": "fact", "lane": "<lane>", "content": "<fact>", "confidence": <float 0-1>, "evidence_refs": ["<ep_id>"]}
2. {"type": "supersede", "old_fact_id": "<fact_id>", "content": "<new_fact>", "evidence_refs": ["<ep_id>"]}
3. {"type": "narrative", "content": "<new_narrative_text>"}

Output ONLY valid JSON.
"""


class Consolidator:
    """Orchestrates the B3 memory digestion loop."""

    def __init__(
        self,
        router: StorageRouter,
        config: Config,
        llm: LLMProvider,
    ) -> None:
        self.router = router
        self.config = config
        self.llm = llm
        
        self.audit = AuditLog(router)
        self.episodes = EpisodeStore(router)
        self.facts = FactStore(router)
        self.narratives = NarrativeStore(router, config)
        self.queue = ProposalQueue(router, config, self.audit)
        self.gates = GatePipeline()

    def run(self, namespace: str) -> Dict[str, Any]:
        """Execute a consolidation run for a single namespace.
        
        Returns a dictionary with statistics about the run.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        stats = {
            "run_id": run_id,
            "episodes_processed": 0,
            "proposals_generated": 0,
            "facts_written": 0,
            "queued": 0,
            "rejected": 0,
        }
        
        # 1. Fetch unconsumed episodes
        unconsumed = self.episodes.list_unconsumed(namespace)
        if not unconsumed:
            return stats
            
        # Apply budget
        batch = unconsumed[:self.config.consolidator.max_episodes_per_run]
        ep_ids = [ep.id for ep in batch]
        stats["episodes_processed"] = len(batch)
        
        # 2. Gather Context (search existing facts based on episode content)
        # For simplicity, we just do a naive text search using the first 50 chars of each episode
        # In B4 this will be enhanced, but this satisfies B3.
        context_facts: Dict[str, Any] = {}
        for ep in batch:
            query = ep.content[:50]
            hits = self.facts.recall(namespace, query, limit=3)
            for hit in hits:
                context_facts[hit.id] = hit.to_dict()
                
        # 3. LLM Generation
        episodes_json = json.dumps([ep.to_dict() for ep in batch], ensure_ascii=False)
        context_json = json.dumps(list(context_facts.values()), ensure_ascii=False)
        
        try:
            proposals = self.llm.generate_proposals(
                _SYSTEM_PROMPT, episodes_json, context_json
            )
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            self.audit.log(namespace, "consolidation_failed", False, reason="gate_error", metadata={"error": str(e)})
            return stats
            
        stats["proposals_generated"] = len(proposals)
        
        # 4 & 5. Gate Pipeline & Commit
        ctx = PipelineContext(run_id, namespace, self.router, self.config)
        # Pre-load episodes for evidence checking (Gate G3)
        for ep in batch:
            ctx.run_episodes[ep.id] = {"origin": ep.origin}
            
        for p in proposals:
            # Default to inference if LLM doesn't specify
            p.setdefault("source", "inference")
            
            res, report = self.gates.evaluate(ctx, p)
            
            if res.decision == "reject":
                stats["rejected"] += 1
                self.audit.log(namespace, "proposal_rejected", False, reason=res.reason, metadata={"report": report})
                
            elif res.decision == "queue":
                stats["queued"] += 1
                prop_id = f"prop_{uuid.uuid4().hex[:16]}"
                self.queue.enqueue(prop_id, run_id, namespace, p.get("type", "unknown"), p, report)
                
            elif res.decision == "pass":
                ptype = p.get("type")
                if ptype == "fact":
                    self.facts.write_fact(namespace, p)
                    stats["facts_written"] += 1
                    ctx.new_facts_count += 1  # budget: count committed facts only
                elif ptype == "supersede":
                    self.facts.supersede_fact(namespace, p)
                    stats["facts_written"] += 1
                    ctx.new_facts_count += 1  # budget: count committed facts only
                elif ptype == "narrative":
                    self.narratives.write(namespace, p["content"], "consolidator")
                    
        # 6. Mark consumed
        self.episodes.mark_consumed(namespace, ep_ids, run_id)
        
        return stats
