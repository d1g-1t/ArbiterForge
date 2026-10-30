from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

GENESIS_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class AuditRecord:
    seq: int
    organization_id: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    prev_hash: str
    event_hash: str = ""


def canonical(record: AuditRecord) -> bytes:
    body = {
        "seq": record.seq,
        "organization_id": record.organization_id,
        "actor_id": record.actor_id,
        "action": record.action,
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "payload": record.payload,
        "prev_hash": record.prev_hash,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def seal(record: AuditRecord, secret: bytes) -> str:
    return hmac.new(secret, canonical(record), hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainVerdict:
    valid: bool
    checked: int
    broken_at_seq: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "checked": self.checked,
            "broken_at_seq": self.broken_at_seq,
            "reason": self.reason,
        }


def verify_chain(records: Iterable[AuditRecord], secret: bytes) -> ChainVerdict:
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for rec in records:
        if rec.seq != expected_seq:
            return ChainVerdict(False, checked, rec.seq, "sequence_gap")
        if rec.prev_hash != expected_prev:
            return ChainVerdict(False, checked, rec.seq, "prev_hash_mismatch")
        if not hmac.compare_digest(seal(rec, secret), rec.event_hash):
            return ChainVerdict(False, checked, rec.seq, "hash_mismatch")
        expected_prev = rec.event_hash
        expected_seq += 1
        checked += 1
    return ChainVerdict(True, checked)
