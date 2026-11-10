from __future__ import annotations

from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from arbiterforge.domain.audit import GENESIS_HASH, AuditRecord, seal, verify_chain

SECRET = b"unit-secret"

payloads = st.dictionaries(st.text(max_size=5), st.integers() | st.text(max_size=5), max_size=3)


def build_chain(items: list[dict]) -> list[AuditRecord]:
    chain: list[AuditRecord] = []
    prev = GENESIS_HASH
    for seq, payload in enumerate(items, start=1):
        rec = AuditRecord(seq, "org", "u", "AwardIssued", "Case", "c1", payload, prev)
        rec = replace(rec, event_hash=seal(rec, SECRET))
        chain.append(rec)
        prev = rec.event_hash
    return chain


@given(st.lists(payloads, min_size=1, max_size=8))
def test_untouched_chain_verifies(items: list[dict]) -> None:
    verdict = verify_chain(build_chain(items), SECRET)
    assert verdict.valid
    assert verdict.checked == len(items)


@given(st.lists(payloads, min_size=1, max_size=8), st.data())
def test_any_payload_tampering_detected(items: list[dict], data: st.DataObject) -> None:
    chain = build_chain(items)
    idx = data.draw(st.integers(0, len(chain) - 1))
    chain[idx] = replace(chain[idx], payload={**chain[idx].payload, "tampered": True})
    verdict = verify_chain(chain, SECRET)
    assert not verdict.valid
    assert verdict.broken_at_seq == idx + 1
    assert verdict.reason == "hash_mismatch"


def test_reordering_gap_and_wrong_secret_detected() -> None:
    chain = build_chain([{"a": 1}, {"b": 2}, {"c": 3}])
    assert verify_chain([chain[0], chain[2]], SECRET).reason == "sequence_gap"
    relinked = [chain[0], replace(chain[1], prev_hash=GENESIS_HASH)]
    assert verify_chain(relinked, SECRET).reason == "prev_hash_mismatch"
    assert verify_chain(chain, b"other").reason == "hash_mismatch"
    assert verify_chain([], SECRET).to_dict() == {
        "valid": True,
        "checked": 0,
        "broken_at_seq": None,
        "reason": None,
    }
