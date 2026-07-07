"""Consolidator Run Loop for Memory Core v2.

The background worker that digests unconsumed episodes into structured facts.
Enforces INV-3 (asynchronous, decoupled from user latency).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .audit import AuditLog
from .config import Config
from .episodes import EpisodeStore, Episode
from .facts import FactStore, AUTHORITY_POLICY
from .gates import GatePipeline, PipelineContext
from .ids import fact_id
from .llm import LLMProvider
from .queue import ProposalQueue
from .router import StorageRouter


logger = logging.getLogger("memory_core.consolidator")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                    self._write_fact(namespace, p)
                    stats["facts_written"] += 1
                elif ptype == "supersede":
                    self._supersede_fact(namespace, p)
                    stats["facts_written"] += 1
                elif ptype == "narrative":
                    # For B3, we just count it. B4 will implement narratives.
                    pass
                    
        # 6. Mark consumed
        self.episodes.mark_consumed(namespace, ep_ids, run_id)
        
        return stats

    def _write_fact(self, namespace: str, p: Dict[str, Any]) -> None:
        lane = p["lane"]
        content = p["content"]
        fid = fact_id(content, lane)
        now = _utc_now_iso()
        
        conn = self.router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO facts (id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed) "
            "VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
            (
                fid, namespace, content,
                p["source"], p["confidence"], lane,
                json.dumps(p.get("evidence_refs", [])),
                now, now
            )
        )
        conn.commit()
        
        self.audit.log(
            namespace, "fact_write", True,
            fact_id=fid, authority_class=lane, source=p["source"],
            reason="human_write" if p["source"] == "trusted_user" else None
        )

    def _supersede_fact(self, namespace: str, p: Dict[str, Any]) -> None:
        old_id = p["old_fact_id"]
        content = p["content"]
        
        conn = self.router.connect(namespace)
        cursor = conn.cursor()
        
        # Get old lane
        cursor.execute("SELECT authority_class FROM facts WHERE id = ?", (old_id,))
        row = cursor.fetchone()
        if not row:
            return
            
        lane = row[0]
        new_fid = fact_id(content, lane)
        now = _utc_now_iso()
        
        cursor.execute(
            "INSERT INTO facts (id, namespace, content, tags, source, confidence, "
            "authority_class, evidence_refs, created_at, last_accessed) "
            "VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
            (
                new_fid, namespace, content,
                p["source"], 1.0, lane,
                json.dumps(p.get("evidence_refs", [])),
                now, now
            )
        )
        
        # Supersede old
        cursor.execute(
            "UPDATE facts SET superseded_by = ? WHERE id = ?",
            (new_fid, old_id)
        )
        conn.commit()
        
        self.audit.log(
            namespace, "fact_supersede", True,
            fact_id=new_fid, authority_class=lane, source=p["source"],
            metadata={"superseded": old_id}
        )
