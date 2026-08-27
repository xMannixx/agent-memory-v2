"""Audit log for Memory Core v2.

Records every write, rejection, approval, and gate decision (INV-7).
Append-only.  Provenance is derived from this log.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .router import StorageRouter
from .utils import utc_now_iso as _utc_now_iso


# Standardized reason codes (spec §7.3)
REASON_CODES = {
    "gate_error",
    "schema_invalid",
    "sanitize_failed",
    "no_evidence_ref",
    "bad_evidence_ref",
    "origin_ceiling",
    "source_not_allowed",
    "low_confidence",
    "budget_exceeded",
    "duplicate",
    "conflict_detected",
    "consolidation_failed",
    "human_approved",
    "human_rejected",
    "human_write",
    "migrated_v3",
    "expired",
    "human_review",
}


class AuditLog:
    """Append-only audit trail."""

    def __init__(self, router: StorageRouter) -> None:
        self._router = router

    def log(
        self,
        namespace: str,
        op: str,
        accepted: bool,
        *,
        fact_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        authority_class: Optional[str] = None,
        source: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record an event in the audit log using a new transaction. Returns the row ID."""
        conn = self._router.connect(namespace)
        cursor = conn.cursor()
        rowid = self.log_txn(
            cursor, namespace, op, accepted,
            fact_id=fact_id, content_hash=content_hash,
            authority_class=authority_class, source=source,
            reason=reason, metadata=metadata,
        )
        conn.commit()
        return rowid

    def log_txn(
        self,
        cursor: Any,
        namespace: str,
        op: str,
        accepted: bool,
        *,
        fact_id: Optional[str] = None,
        content_hash: Optional[str] = None,
        authority_class: Optional[str] = None,
        source: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Record an event in the audit log using an existing cursor."""
        if reason and reason not in REASON_CODES:
            raise ValueError(f"Unknown reason code: {reason}")

        meta_json = None
        if metadata:
            meta_json = json.dumps(metadata, ensure_ascii=False)

        cursor.execute(
            "INSERT INTO memory_audit "
            "(namespace, ts, op, fact_id, content_hash, authority_class, "
            "source, accepted, reason, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                namespace,
                _utc_now_iso(),
                op,
                fact_id,
                content_hash,
                authority_class,
                source,
                1 if accepted else 0,
                reason,
                meta_json,
            ),
        )
        return cursor.lastrowid or 0
