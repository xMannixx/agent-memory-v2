"""Gate Pipeline for Memory Core v2.

Deterministic evaluation of proposals from the consolidator.
Enforces INV-4, INV-5, INV-6, INV-8, INV-9.

Gates (spec §7.3):
G1 Schema
G2 Sanitization
G3 Evidence
G4 Origin ceiling
G5 Lane policy
G6 Dedup
G7 Conflict
G8 Budget
G9 Routing
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Set

from .config import Config
from .episodes import VALID_ORIGINS
from .facts import AUTHORITY_POLICY
from .ids import fact_id
from .router import StorageRouter


@dataclass(frozen=True)
class GateResult:
    decision: str  # "pass", "reject", "queue"
    reason: Optional[str] = None
    info: Optional[str] = None


class PipelineContext:
    """State for a single proposal evaluation within a run."""
    def __init__(self, run_id: str, namespace: str, router: StorageRouter, config: Config):
        self.run_id = run_id
        self.namespace = namespace
        self.router = router
        self.config = config
        
        # State tracking for G8 (Budget)
        self.new_facts_count = 0
        
        # Load run's available unconsumed episodes for G3
        self.run_episodes: Dict[str, Dict[str, Any]] = {}
        self._load_unconsumed_episodes()
        
    def _load_unconsumed_episodes(self):
        conn = self.router.connect(self.namespace)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, origin FROM episodes "
            "WHERE namespace = ? AND consumed_by IS NULL",
            (self.namespace,)
        )
        for row in cursor.fetchall():
            self.run_episodes[row[0]] = {"origin": row[1]}


class GatePipeline:
    """The G1-G9 deterministic pipeline."""
    
    def evaluate(self, ctx: PipelineContext, proposal: Dict[str, Any]) -> Tuple[GateResult, Dict[str, Any]]:
        """Run a proposal through all gates. Returns the final result and a report of all gates.

        The proposal is copied before evaluation so that gates can never
        mutate the caller's data (fixes INV-6 side-effect violation).
        """
        import copy
        proposal = copy.deepcopy(proposal)
        report = {}
        
        gates = [
            ("G1", self._g1_schema),
            ("G2", self._g2_sanitization),
            ("G3", self._g3_evidence),
            ("G4", self._g4_origin_ceiling),
            ("G5", self._g5_lane_policy),
            ("G6", self._g6_dedup),
            ("G7", self._g7_conflict),
            ("G8", self._g8_budget),
            ("G9", self._g9_routing),
        ]
        
        for name, gate_func in gates:
            try:
                res = gate_func(ctx, proposal)
                report[name] = {"decision": res.decision, "reason": res.reason, "info": res.info}
                if res.decision != "pass":
                    return res, report
            except Exception as e:
                # INV-6: Fail-closed gates
                err_res = GateResult("reject", "gate_error", str(e))
                report[name] = {"decision": err_res.decision, "reason": err_res.reason, "info": err_res.info}
                return err_res, report
                
        # If we reached here, G9 passed (which actually returns "pass" for auto-accept or "queue" for queueing)
        return res, report

    def _g1_schema(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype not in {"fact", "supersede", "narrative", "rule"}:
            return GateResult("reject", "schema_invalid", f"Unknown type {ptype}")
            
        if ptype == "fact":
            if not isinstance(p.get("content"), str) or not p["content"].strip():
                return GateResult("reject", "schema_invalid", "Empty content")
            if p.get("lane") not in AUTHORITY_POLICY:
                return GateResult("reject", "schema_invalid", f"Unknown lane {p.get('lane')}")
            if not isinstance(p.get("confidence"), (int, float)) or not (0.0 <= p["confidence"] <= 1.0):
                return GateResult("reject", "schema_invalid", "Confidence must be between 0 and 1")
            
        elif ptype == "supersede":
            if not isinstance(p.get("old_fact_id"), str):
                return GateResult("reject", "schema_invalid", "Missing old_fact_id")
            if not isinstance(p.get("content"), str) or not p["content"].strip():
                return GateResult("reject", "schema_invalid", "Empty content")
                
        elif ptype == "narrative":
            if not isinstance(p.get("content"), str) or not p["content"].strip():
                return GateResult("reject", "schema_invalid", "Empty content")
                
        return GateResult("pass")

    def _g2_sanitization(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        content = p.get("content", "")
        
        # Clean control chars (except newline)
        content = "".join(ch for ch in content if ord(ch) >= 32 or ch == '\n')
        
        # Check injection patterns (extended list)
        lower_content = content.lower()
        _INJECTION_PATTERNS = (
            "```", "system:", "ignore previous",
            "ignore all", "disregard", "override instructions",
            "you are now", "forget your",
        )
        if any(pat in lower_content for pat in _INJECTION_PATTERNS):
            return GateResult("reject", "sanitize_failed", "Injection pattern detected")
            
        # Write back cleaned content (safe: we already work on a copy)
        p["content"] = content.strip()
        
        # Length caps — use lane policy content_max_chars, not injection config
        ptype = p.get("type")
        if ptype in ("fact", "supersede"):
            lane = p.get("lane", "evidence")
            policy = AUTHORITY_POLICY.get(lane, AUTHORITY_POLICY["evidence"])
            cap = policy.get("content_max_chars", 2000)
            if len(p["content"]) > cap:
                return GateResult("reject", "sanitize_failed", f"Content exceeds lane cap {cap}")
        elif ptype == "narrative":
            cap = ctx.config.narrative.max_chars
            if len(p["content"]) > cap:
                return GateResult("reject", "sanitize_failed", f"Narrative exceeds cap {cap}")
                
        return GateResult("pass")

    def _g3_evidence(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype in ("fact", "supersede"):
            refs = p.get("evidence_refs", [])
            if not isinstance(refs, list) or not refs:
                return GateResult("reject", "no_evidence_ref", "Missing evidence_refs")
            
            for ref in refs:
                if ref not in ctx.run_episodes:
                    return GateResult("reject", "bad_evidence_ref", f"Unknown or already consumed episode {ref}")
                    
        return GateResult("pass")

    def _g4_origin_ceiling(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype in ("fact", "supersede"):
            refs = p.get("evidence_refs", [])
            
            # Gather origins for all refs
            origins = set(ctx.run_episodes[ref]["origin"] for ref in refs)
            
            weakest_is_untrusted = bool(origins & {"external_web", "external_document", "unknown"})
            
            if ptype == "fact":
                lane = p.get("lane")
                if weakest_is_untrusted and lane != "evidence":
                    return GateResult("reject", "origin_ceiling", f"Untrusted origin restricts to evidence lane, requested {lane}")
                if lane == "identity" and origins - {"trusted_user", "local_project"}:
                    return GateResult("reject", "origin_ceiling", "Identity requires all refs to be trusted")
                if lane == "authorization" and origins - {"trusted_user", "local_project"}:
                    return GateResult("reject", "origin_ceiling", "Authorization requires all refs to be trusted")
            
            elif ptype == "supersede":
                # We need to know the lane of the old fact. We fetch it here.
                old_id = p.get("old_fact_id")
                conn = ctx.router.connect(ctx.namespace)
                cursor = conn.cursor()
                cursor.execute("SELECT authority_class FROM facts WHERE id = ?", (old_id,))
                row = cursor.fetchone()
                if not row:
                    return GateResult("reject", "origin_ceiling", "Old fact not found")
                lane = row[0]
                if weakest_is_untrusted and lane != "evidence":
                    return GateResult("reject", "origin_ceiling", f"Untrusted origin restricts supersede to evidence lane, old fact is {lane}")
                if lane in ("identity", "authorization") and origins - {"trusted_user", "local_project"}:
                    return GateResult("reject", "origin_ceiling", f"{lane} requires all refs to be trusted")
                    
        return GateResult("pass")

    def _g5_lane_policy(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype == "fact":
            lane = p.get("lane")
            policy = AUTHORITY_POLICY.get(lane)
            
            source = p.get("source", "inference")
            if source not in policy["allowed_sources"]:
                return GateResult("reject", "source_not_allowed", f"Source {source} not allowed in {lane}")
                
            if p.get("confidence", 0) < policy["min_confidence"]:
                return GateResult("reject", "low_confidence", f"Confidence below {lane} minimum {policy['min_confidence']}")
                
        return GateResult("pass")

    def _g6_dedup(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype == "fact":
            lane = p.get("lane")
            fid = fact_id(p["content"], lane)
            conn = ctx.router.connect(ctx.namespace)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM facts WHERE id = ?", (fid,))
            if cursor.fetchone():
                return GateResult("reject", "duplicate", "Fact already exists")
        elif ptype == "supersede":
            # Check that the new content doesn't already exist as an active fact
            old_id = p.get("old_fact_id")
            conn = ctx.router.connect(ctx.namespace)
            cursor = conn.cursor()
            cursor.execute("SELECT authority_class FROM facts WHERE id = ?", (old_id,))
            row = cursor.fetchone()
            if row:
                lane = row[0]
                new_fid = fact_id(p["content"], lane)
                cursor.execute("SELECT 1 FROM facts WHERE id = ?", (new_fid,))
                if cursor.fetchone():
                    return GateResult("reject", "duplicate", "Supersede target already exists as fact")
                
        return GateResult("pass")

    def _g7_conflict(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype == "fact":
            lane = p.get("lane")
            policy = AUTHORITY_POLICY.get(lane)
            if policy["single_valued"]:
                conn = ctx.router.connect(ctx.namespace)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM facts WHERE namespace = ? AND authority_class = ? AND superseded_by IS NULL",
                    (ctx.namespace, lane),
                )
                existing = cursor.fetchall()
                if existing:
                    return GateResult("queue", "conflict_detected", f"Single-valued lane {lane} has {len(existing)} active fact(s)")
        elif ptype == "supersede":
            # For supersede on single-valued lanes, also queue if multiple active facts exist
            old_id = p.get("old_fact_id")
            conn = ctx.router.connect(ctx.namespace)
            cursor = conn.cursor()
            cursor.execute("SELECT authority_class FROM facts WHERE id = ?", (old_id,))
            row = cursor.fetchone()
            if row:
                lane = row[0]
                policy = AUTHORITY_POLICY.get(lane)
                if policy and policy["single_valued"]:
                    cursor.execute(
                        "SELECT id FROM facts WHERE namespace = ? AND authority_class = ? AND superseded_by IS NULL",
                        (ctx.namespace, lane),
                    )
                    existing = cursor.fetchall()
                    if len(existing) > 1:
                        return GateResult("queue", "conflict_detected", f"Single-valued lane {lane} has {len(existing)} active facts, supersede needs review")
                    
        return GateResult("pass")

    def _g8_budget(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        if ptype == "fact":
            if ctx.new_facts_count >= ctx.config.consolidator.max_new_facts_per_run:
                return GateResult("reject", "budget_exceeded", "Run budget exceeded")
            # Budget is incremented in the consolidator after commit, not here,
            # so that queued proposals do not consume the run budget.
            
        return GateResult("pass")

    def _g9_routing(self, ctx: PipelineContext, p: Dict[str, Any]) -> GateResult:
        ptype = p.get("type")
        
        if ctx.namespace == "shared":
            # INV-10: shared namespace accepts writes only via the review queue
            return GateResult("queue", "human_review", "Writes to shared must be reviewed")
            
        if ptype == "fact":
            lane = p.get("lane")
            if lane in ("identity", "authorization", "procedural"):
                return GateResult("queue", "human_review", f"Lane {lane} always requires review")
            return GateResult("pass")
            
        elif ptype == "narrative":
            if ctx.config.narrative.review:
                return GateResult("queue", "human_review", "Narrative review enforced by config")
            return GateResult("pass")
            
        elif ptype == "supersede":
            # Depends on lane of old fact
            old_id = p.get("old_fact_id")
            conn = ctx.router.connect(ctx.namespace)
            cursor = conn.cursor()
            cursor.execute("SELECT authority_class FROM facts WHERE id = ?", (old_id,))
            row = cursor.fetchone()
            if row:
                lane = row[0]
                if lane in ("identity", "authorization", "procedural"):
                    return GateResult("queue", "human_review", f"Superseding in {lane} requires review")
            return GateResult("pass")
            
        elif ptype == "rule":
            return GateResult("queue", "human_review", "Rules always require review")
            
        return GateResult("pass")
