"""Matter-wide legal-hold workflow tests (Gap 6).

The ledger wraps the existing per-record legal_hold=True primitive +
WorkspaceDirectory.set_hold with the issuance → acknowledgment → release
workflow that litigation-hold defensibility requires. These tests pin the
state transitions, the stack-blocking, the withdraw path, and the
matter_under_hold query that downstream disposition paths rely on.
"""
from __future__ import annotations

import pytest

from hybridagent_praxis_legal.modules.legal_hold import (
    LegalHoldError,
    LegalHoldLedger,
    render_matter_summary,
)

# ---------------------------------------------------------------------------
# issue

def test_issue_creates_active_hold():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="atty-1", custodian="c-1",
                     scope="all emails re: Smith v Jones",
                     reason="litigation filed 2026-07-16")
    assert h.status == "issued"
    assert h.is_active
    assert ledger.matter_under_hold("ws-1")
    assert ledger.active_holds("ws-1") == [h]


@pytest.mark.parametrize("missing", [
    "matter_id", "issued_by", "custodian", "scope", "reason",
])
def test_issue_requires_all_fields(missing):
    ledger = LegalHoldLedger()
    kwargs = dict(matter_id="ws-1", issued_by="atty-1", custodian="c-1",
                  scope="scope", reason="reason")
    kwargs[missing] = "  "  # whitespace-only should fail too
    with pytest.raises(LegalHoldError, match=missing):
        ledger.issue(**kwargs)


def test_issue_blocks_stacking_active_hold():
    """Don't stack two active holds on the same matter — release the old one first."""
    ledger = LegalHoldLedger()
    ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                 scope="s", reason="r")
    with pytest.raises(LegalHoldError, match="already has an active hold"):
        ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s2", reason="r2")


def test_issue_after_release_allowed():
    ledger = LegalHoldLedger()
    h1 = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                      scope="s", reason="r1")
    ledger.release(hold_id=h1.hold_id, released_by="a", release_reason="settled")
    h2 = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                      scope="s2", reason="r2")
    assert h2.is_active
    assert ledger.matter_under_hold("ws-1")


def test_issue_after_withdraw_allowed():
    ledger = LegalHoldLedger()
    h1 = ledger.issue(matter_id="ws-2", issued_by="a", custodian="c",
                      scope="s", reason="r")
    ledger.withdraw(hold_id=h1.hold_id, withdrawn_by="a", reason="error")
    h2 = ledger.issue(matter_id="ws-2", issued_by="a", custodian="c",
                      scope="s2", reason="r2")
    assert h2.is_active


# ---------------------------------------------------------------------------
# acknowledge

def test_acknowledge_transitions_to_acknowledged():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    h2 = ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="custodian-1")
    assert h2.status == "acknowledged"
    assert h2.is_acknowledged
    assert h2.acknowledged_by == "custodian-1"
    assert h2.acknowledged_at > 0


def test_acknowledge_requires_acknowledged_by():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    with pytest.raises(LegalHoldError, match="acknowledged_by"):
        ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="  ")


def test_cannot_acknowledge_unknown_hold():
    ledger = LegalHoldLedger()
    with pytest.raises(LegalHoldError, match="not found"):
        ledger.acknowledge(hold_id="nope", acknowledged_by="c")


def test_cannot_acknowledge_already_acknowledged():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="c")
    with pytest.raises(LegalHoldError, match="cannot acknowledge"):
        ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="c")


def test_cannot_acknowledge_released_hold():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    ledger.release(hold_id=h.hold_id, released_by="a", release_reason="settled")
    with pytest.raises(LegalHoldError, match="cannot acknowledge"):
        ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="c")


# ---------------------------------------------------------------------------
# release

def test_release_transitions_to_released():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    h2 = ledger.release(hold_id=h.hold_id, released_by="atty-1",
                        release_reason="case settled")
    assert h2.status == "released"
    assert not h2.is_active
    assert not ledger.matter_under_hold("ws-1")


def test_release_after_acknowledgment():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="c")
    h2 = ledger.release(hold_id=h.hold_id, released_by="a",
                        release_reason="settled")
    assert h2.status == "released"


def test_release_requires_fields():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    with pytest.raises(LegalHoldError, match="released_by"):
        ledger.release(hold_id=h.hold_id, released_by="  ", release_reason="r")
    with pytest.raises(LegalHoldError, match="release_reason"):
        ledger.release(hold_id=h.hold_id, released_by="a", release_reason="  ")


def test_cannot_release_unknown_hold():
    ledger = LegalHoldLedger()
    with pytest.raises(LegalHoldError, match="not found"):
        ledger.release(hold_id="nope", released_by="a", release_reason="r")


def test_cannot_release_already_released():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    ledger.release(hold_id=h.hold_id, released_by="a", release_reason="r")
    with pytest.raises(LegalHoldError, match="cannot release"):
        ledger.release(hold_id=h.hold_id, released_by="a", release_reason="r")


# ---------------------------------------------------------------------------
# withdraw (rescind before acknowledgment)

def test_withdraw_transitions_to_withdrawn():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    h2 = ledger.withdraw(hold_id=h.hold_id, withdrawn_by="a", reason="issued in error")
    assert h2.status == "withdrawn"
    assert not h2.is_active
    assert "WITHDRAWN" in h2.release_reason


def test_cannot_withdraw_after_acknowledgment():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="c")
    with pytest.raises(LegalHoldError, match="cannot withdraw"):
        ledger.withdraw(hold_id=h.hold_id, withdrawn_by="a", reason="x")


# ---------------------------------------------------------------------------
# queries

def test_matter_under_hold_false_for_unknown_matter():
    ledger = LegalHoldLedger()
    assert not ledger.matter_under_hold("nope")
    assert ledger.active_holds("nope") == []
    assert ledger.history("nope") == []
    assert ledger.latest("nope") is None


def test_history_returns_all_holds_for_matter():
    ledger = LegalHoldLedger()
    h1 = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                      scope="s", reason="r1")
    ledger.release(hold_id=h1.hold_id, released_by="a", release_reason="done")
    h2 = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                      scope="s", reason="r2")
    history = ledger.history("ws-1")
    assert len(history) == 2
    assert ledger.latest("ws-1").hold_id == h2.hold_id


def test_get_returns_hold_by_id():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r")
    assert ledger.get(h.hold_id) is h
    assert ledger.get("nope") is None


def test_all_holds_across_matters():
    ledger = LegalHoldLedger()
    ledger.issue(matter_id="ws-1", issued_by="a", custodian="c", scope="s", reason="r")
    ledger.issue(matter_id="ws-2", issued_by="a", custodian="c", scope="s", reason="r")
    assert len(ledger.all_holds()) == 2


# ---------------------------------------------------------------------------
# render

def test_render_shows_holds_and_active_count():
    ledger = LegalHoldLedger()
    h1 = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                      scope="emails re: Smith", reason="litigation 2026-07-16")
    ledger.acknowledge(hold_id=h1.hold_id, acknowledged_by="c")
    ledger.release(hold_id=h1.hold_id, released_by="a", release_reason="settled")
    ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                 scope="new matter", reason="new case")
    out = render_matter_summary("ws-1", ledger)
    assert "Legal-Hold Summary — matter ws-1" in out
    assert "Total holds on record: 2" in out
    assert "Active holds: 1" in out
    assert "RELEASED" in out
    assert "ISSUED" in out


def test_render_no_holds():
    out = render_matter_summary("ws-9", LegalHoldLedger())
    assert "No holds on record" in out


# ---------------------------------------------------------------------------
# timestamp injection (deterministic tests)

def test_now_parameter_makes_timestamps_deterministic():
    ledger = LegalHoldLedger()
    h = ledger.issue(matter_id="ws-1", issued_by="a", custodian="c",
                     scope="s", reason="r", now=1000.0)
    assert h.issued_at == 1000.0
    h2 = ledger.acknowledge(hold_id=h.hold_id, acknowledged_by="c", now=2000.0)
    assert h2.acknowledged_at == 2000.0