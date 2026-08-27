"""Content-hash ID generation for Memory Core v2.

All IDs are SHA-256 derived, truncated to 16 hex chars, and prefixed by
entity type.  This guarantees idempotency: the same inputs always produce
the same ID.

Prefixes (spec §4):
    ep_   episode
    f_    fact
    n_    narrative version
    p_    proposal
    r_    procedural rule
    e_    entity
    rel_  relation
    l_    lesson
"""

from __future__ import annotations

import hashlib


def make_id(prefix: str, *parts: str) -> str:
    """Generate a deterministic, content-hash ID.

    >>> make_id("ep_", "hello", "world")  # doctest: +SKIP
    'ep_936a185caaa266bb'
    """
    raw = "|".join(parts).encode("utf-8")
    return prefix + hashlib.sha256(raw).hexdigest()[:16]


def episode_id(content: str, session_id: str, created_at: str) -> str:
    """ID for an episode: ``ep_<hash(content+session+ts)>``."""
    return make_id("ep_", content, session_id or "", created_at)


def fact_id(content: str, authority_class: str) -> str:
    """ID for a fact: ``f_<hash(content+lane)>``."""
    return make_id("f_", content, authority_class)


def narrative_id(namespace: str, version: int) -> str:
    """ID for a narrative version: ``n_<hash(namespace+version)>``."""
    return make_id("n_", namespace, str(version))


def proposal_id(*parts: str) -> str:
    """ID for a proposal: ``p_<hash(parts)>``."""
    return make_id("p_", *parts)


def rule_id(domain: str, trigger_json: str, effect_json: str,
            behavior_text: str) -> str:
    """ID for a procedural rule: ``r_<hash(domain+trigger+effect+text)>``."""
    return make_id("r_", domain, trigger_json, effect_json, behavior_text)


def entity_id(name: str, entity_type: str) -> str:
    """ID for an entity: ``e_<hash(name+type)>``."""
    return make_id("e_", name, entity_type)


def relation_id(from_name: str, predicate: str, to_name: str) -> str:
    """ID for a relation: ``rel_<hash(from+predicate+to)>``."""
    return make_id("rel_", from_name, predicate, to_name)


def lesson_id(action: str, context: str) -> str:
    """ID for a lesson: ``l_<hash(action+context)>``."""
    return make_id("l_", action, context)
