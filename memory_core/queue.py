"""Proposal queue for Memory Core v2.

Handles pending privileged writes (INV-5) and human review operations.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .audit import AuditLog
from .config import Config
from .ids import fact_id
from .models import Proposal, _json_loads_safe
from .router import StorageRouter
from .utils import utc_now_iso


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_proposal(row: tuple) -> Proposal:
    return Proposal(
        id=row["id"],
        run_id=row["run_id"],
        namespace=row["namespace"],
        proposal_type=row["proposal_type"],
        payload=_json_loads_safe(row["payload"], {}),
        status=row["status"],
        gate_report=_json_loads_safe(row["gate_report"], {}),
        created_at=row["created_at"],
        decided_at=row["decided_at"],
        decided_by=row[9],
    )


class ProposalQueue:
    """Manages the proposal_queue table."""

    def __init__(
        self,
        router: StorageRouter,
        config: Config,
        audit: AuditLog,
    ) -> None:
        self._router = router
        self._config = config
        self._audit = audit
        self._ttl_days = config.consolidator.review_ttl_days

    def enqueue(
        self,
        proposal_id: str,
        run_id: str,
        namespace: str,
        proposal_type: str,
        payload: Dict[str, Any],
        gate_report: Dict[str, Any],
    ) -> None:
        """Insert a proposal into the pending queue."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        
        # Idempotency
        cursor.execute("SELECT 1 FROM proposal_queue WHERE id = ?", (proposal_id,))
        if cursor.fetchone():
            return
            
        cursor.execute(
            "INSERT INTO proposal_queue "
            "(id, run_id, namespace, proposal_type, payload, status, "
            "gate_report, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                proposal_id,
                run_id,
                namespace,
                proposal_type,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(gate_report, ensure_ascii=False),
                _utc_now().isoformat(),
            )
        )
        conn.commit()
        
        self._audit.log(
            namespace=namespace,
            op="proposal_queued",
            accepted=True,
            metadata={"proposal_id": proposal_id, "type": proposal_type}
        )

    def list_pending(self, namespace: str, *, limit: int = 100) -> List[Proposal]:
        """List all pending proposals for a namespace."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, run_id, namespace, proposal_type, payload, status, "
            "gate_report, created_at, decided_at, decided_by "
            "FROM proposal_queue "
            "WHERE namespace = ? AND status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?",
            (namespace, limit)
        )
        return [_row_to_proposal(row) for row in cursor.fetchall()]

    def get(self, namespace: str, proposal_id: str) -> Optional[Proposal]:
        """Get a specific proposal by ID."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, run_id, namespace, proposal_type, payload, status, "
            "gate_report, created_at, decided_at, decided_by "
            "FROM proposal_queue "
            "WHERE namespace = ? AND id = ?",
            (namespace, proposal_id)
        )
        row = cursor.fetchone()
        return _row_to_proposal(row) if row else None

    def approve(self, namespace: str, proposal_id: str, by: str) -> bool:
        """Approve a proposal and atomically commit its payload.

        Uses BEGIN IMMEDIATE to acquire a write lock before reading,
        preventing race conditions with concurrent approvers.

        Returns ``False`` if the proposal does not exist or is not pending.
        """
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        now = utc_now_iso()

        try:
            # Acquire write lock immediately to prevent race conditions.
            cursor.execute("BEGIN IMMEDIATE")

            # Read proposal under write lock.
            cursor.execute(
                "SELECT id, run_id, namespace, proposal_type, payload, status, "
                "gate_report, created_at, decided_at, decided_by "
                "FROM proposal_queue "
                "WHERE namespace = ? AND id = ? AND status = 'pending'",
                (namespace, proposal_id),
            )
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return False

            proposal = _row_to_proposal(row)
            ptype = proposal.proposal_type
            payload = proposal.payload

            if ptype == "fact":
                fid = fact_id(payload["content"], payload["lane"])
                cursor.execute(
                    "INSERT OR IGNORE INTO facts "
                    "(id, namespace, content, tags, source, confidence, "
                    "authority_class, evidence_refs, created_at, last_accessed) "
                    "VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
                    (
                        fid, namespace, payload["content"],
                        payload.get("source", "inference"),
                        payload.get("confidence", 1.0),
                        payload["lane"],
                        json.dumps(payload.get("evidence_refs", [])),
                        now, now,
                    ),
                )
            elif ptype == "supersede":
                old_id = payload["old_fact_id"]
                cursor.execute(
                    "SELECT authority_class FROM facts WHERE id = ?", (old_id,),
                )
                row2 = cursor.fetchone()
                lane = row2[0] if row2 else "evidence"
                new_fid = fact_id(payload["content"], lane)
                cursor.execute(
                    "INSERT OR IGNORE INTO facts "
                    "(id, namespace, content, tags, source, confidence, "
                    "authority_class, evidence_refs, created_at, last_accessed) "
                    "VALUES (?, ?, ?, '[]', ?, ?, ?, ?, ?, ?)",
                    (
                        new_fid, namespace, payload["content"],
                        payload.get("source", "inference"), 1.0, lane,
                        json.dumps(payload.get("evidence_refs", [])),
                        now, now,
                    ),
                )
                cursor.execute(
                    "UPDATE facts SET superseded_by = ? WHERE id = ?",
                    (new_fid, old_id),
                )
            elif ptype == "narrative":
                cursor.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM narratives "
                    "WHERE namespace = ?",
                    (namespace,),
                )
                next_version = cursor.fetchone()[0] + 1
                from .ids import narrative_id as _nar_id
                nar_id = _nar_id(namespace, next_version)
                cursor.execute(
                    "INSERT OR IGNORE INTO narratives "
                    "(id, namespace, version, content, created_at, created_by) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (nar_id, namespace, next_version, payload["content"], now, by),
                )

            # Flip queue status.
            cursor.execute(
                "UPDATE proposal_queue "
                "SET status = 'approved', decided_at = ?, decided_by = ? "
                "WHERE namespace = ? AND id = ? AND status = 'pending'",
                (now, by, namespace, proposal_id),
            )
            
            self._audit.log_txn(
                cursor,
                namespace=namespace,
                op="proposal_approved",
                accepted=True,
                reason="human_approved",
                metadata={"proposal_id": proposal_id, "by": by},
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return True

    def reject(self, namespace: str, proposal_id: str, by: str) -> bool:
        """Mark a proposal as rejected."""
        return self._decide(namespace, proposal_id, "rejected", by, "human_rejected")

    def _decide(self, namespace: str, proposal_id: str, status: str, by: str, reason: str) -> bool:
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "UPDATE proposal_queue "
                "SET status = ?, decided_at = ?, decided_by = ? "
                "WHERE namespace = ? AND id = ? AND status = 'pending'",
                (status, _utc_now().isoformat(), by, namespace, proposal_id)
            )
            if cursor.rowcount == 0:
                conn.rollback()
                return False
                
            self._audit.log_txn(
                cursor,
                namespace=namespace,
                op=f"proposal_{status}",
                accepted=(status == "approved"),
                reason=reason,
                metadata={"proposal_id": proposal_id, "by": by}
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
            
        return True

    def expire_stale(self, namespace: str) -> int:
        """Mark old pending proposals as expired. Returns count updated."""
        cutoff = _utc_now() - timedelta(days=self._ttl_days)
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        
        # Get IDs first for audit
        cursor.execute(
            "SELECT id FROM proposal_queue "
            "WHERE namespace = ? AND status = 'pending' AND created_at < ?",
            (namespace, cutoff.isoformat())
        )
        expired_ids = [row[0] for row in cursor.fetchall()]
        if not expired_ids:
            return 0
            
        placeholders = ",".join("?" for _ in expired_ids)
        cursor.execute(
            f"UPDATE proposal_queue SET status = 'expired' "
            f"WHERE namespace = ? AND id IN ({placeholders})",
            [namespace] + expired_ids
        )
        conn.commit()
        
        for eid in expired_ids:
            self._audit.log(
                namespace=namespace,
                op="proposal_expired",
                accepted=False,
                reason="expired",
                metadata={"proposal_id": eid}
            )
            
        return len(expired_ids)
