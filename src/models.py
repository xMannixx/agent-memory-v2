"""Data models for Memory Core v2.

Frozen dataclasses for the four primary storage types.  Each model mirrors
the corresponding SQLite table (spec §4) and carries a ``to_dict()`` helper
for JSON serialisation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# -- Episode (§4.1) ---------------------------------------------------------

@dataclass(frozen=True)
class Episode:
    """An append-only raw interaction record."""

    id: str
    namespace: str
    session_id: Optional[str]
    role: str            # user | assistant | tool | system
    origin: str          # Guard vocabulary (§6.2)
    content: str
    metadata: Dict[str, Any]
    created_at: str
    expires_at: Optional[str]
    consumed_by: Optional[str]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "session_id": self.session_id,
            "role": self.role,
            "origin": self.origin,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "consumed_by": self.consumed_by,
        }


# -- Fact (§4.2) -------------------------------------------------------------

@dataclass(frozen=True)
class Fact:
    """A semantic memory fact within an Authority Lane."""

    id: str
    namespace: str
    content: str
    tags: List[str]
    source: str
    confidence: float
    authority_class: str
    evidence_refs: List[str]
    created_at: str
    last_accessed: str
    access_count: int
    expires_at: Optional[str]
    superseded_by: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "content": self.content,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "authority_class": self.authority_class,
            "evidence_refs": self.evidence_refs,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "expires_at": self.expires_at,
            "superseded_by": self.superseded_by,
        }


# -- Narrative (§4.3) --------------------------------------------------------

@dataclass(frozen=True)
class Narrative:
    """A curated profile document version for a namespace."""

    id: str
    namespace: str
    version: int
    content: str
    created_at: str
    created_by: str  # run_id or 'human'

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "version": self.version,
            "content": self.content,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }


# -- Proposal (§4.4) ---------------------------------------------------------

@dataclass(frozen=True)
class Proposal:
    """A consolidator proposal awaiting review."""

    id: str
    run_id: str
    namespace: str
    proposal_type: str   # fact | supersede | narrative | rule
    payload: Dict[str, Any]
    status: str          # pending | approved | rejected | expired
    gate_report: Dict[str, Any]
    created_at: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "namespace": self.namespace,
            "proposal_type": self.proposal_type,
            "payload": self.payload,
            "status": self.status,
            "gate_report": self.gate_report,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
        }


# -- Lesson (carried from v3.6) ----------------------------------------------

@dataclass(frozen=True)
class Lesson:
    """A recorded positive or negative lesson."""

    id: str
    namespace: str
    action: str
    context: str
    outcome: str
    insight: str
    created_at: str
    last_accessed: Optional[str] = None
    expires_at: Optional[str] = None
    applied_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "action": self.action,
            "context": self.context,
            "outcome": self.outcome,
            "insight": self.insight,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "expires_at": self.expires_at,
            "applied_count": self.applied_count,
        }


# -- Entity (carried from v3.6) ----------------------------------------------

@dataclass(frozen=True)
class Entity:
    """A tracked real-world entity."""

    id: str
    namespace: str
    name: str
    entity_type: str
    attributes: Dict[str, Any]
    first_seen: str
    last_updated: str
    last_accessed: Optional[str] = None
    expires_at: Optional[str] = None
    fact_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "name": self.name,
            "entity_type": self.entity_type,
            "attributes": self.attributes,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
            "last_accessed": self.last_accessed,
            "expires_at": self.expires_at,
            "fact_ids": self.fact_ids,
        }


# -- Row conversion helpers ---------------------------------------------------

def _json_loads_safe(raw: Any, default: Any = None) -> Any:
    """Parse a JSON string, returning *default* on failure or non-string."""
    if raw is None:
        return default if default is not None else {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def row_to_episode(row: tuple) -> Episode:
    """Convert a DB row to an Episode (column order must match SELECT)."""
    return Episode(
        id=row[0],
        namespace=row[1],
        session_id=row[2],
        role=row[3],
        origin=row[4],
        content=row[5],
        metadata=_json_loads_safe(row[6], {}),
        created_at=row[7],
        expires_at=row[8],
        consumed_by=row[9],
    )


def row_to_fact(row: tuple) -> Fact:
    """Convert a DB row to a Fact (column order must match SELECT)."""
    return Fact(
        id=row[0],
        namespace=row[1],
        content=row[2],
        tags=_json_loads_safe(row[3], []),
        source=row[4],
        confidence=row[5],
        authority_class=row[6],
        evidence_refs=_json_loads_safe(row[7], []),
        created_at=row[8],
        last_accessed=row[9],
        access_count=row[10],
        expires_at=row[11],
        superseded_by=row[12] if len(row) > 12 else None,
    )


def row_to_narrative(row: tuple) -> Narrative:
    """Convert a DB row to a Narrative."""
    return Narrative(
        id=row[0],
        namespace=row[1],
        version=row[2],
        content=row[3],
        created_at=row[4],
        created_by=row[5],
    )


def row_to_lesson(row: tuple) -> Lesson:
    """Convert a DB row to a Lesson."""
    return Lesson(
        id=row[0],
        namespace=row[1],
        action=row[2],
        context=row[3],
        outcome=row[4],
        insight=row[5],
        created_at=row[6],
        last_accessed=row[7] if len(row) > 7 else None,
        expires_at=row[8] if len(row) > 8 else None,
        applied_count=row[9] if len(row) > 9 else 0,
    )


def row_to_entity(row: tuple) -> Entity:
    """Convert a DB row to an Entity."""
    return Entity(
        id=row[0],
        namespace=row[1],
        name=row[2],
        entity_type=row[3],
        attributes=_json_loads_safe(row[4], {}),
        first_seen=row[5],
        last_updated=row[6],
        last_accessed=row[7] if len(row) > 7 else None,
        expires_at=row[8] if len(row) > 8 else None,
        fact_ids=_json_loads_safe(row[9], []) if len(row) > 9 else [],
    )
