"""Regression coverage for release-blocking legal compliance failures."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from hybridagent_praxis_legal.modules import security_attestation
from hybridagent_praxis_legal.modules.advertising_filing import (
    AdvertisingFiling,
    FilingLedger,
    can_send,
    validate_before_send,
)
from hybridagent_praxis_legal.modules.credentials import (
    CESession,
    Credential,
    compliance_status,
    credential_for,
    record_hours,
)
from hybridagent_praxis_legal.modules.legal_hold import LegalHoldError, LegalHoldLedger


def _approved(**changes):
    values = {
        "artifact_id": "ad-1",
        "jurisdiction": "NY",
        "status": "approved",
        "filed_at": "2026-07-01",
        "filing_number": "NY-1",
        "filed_by": "attorney-1",
        "authority": "NY Appellate Division",
        "disclaimers_present": True,
        "label_present": True,
    }
    values.update(changes)
    return AdvertisingFiling(**values)


def test_advertising_gate_fails_closed_for_unknown_state_and_status():
    assert not can_send(_approved(jurisdiction="ZZ"))
    invalid = _approved(status="not-a-status")
    assert not can_send(invalid)
    assert any(item.field == "status" for item in validate_before_send(invalid))


@pytest.mark.parametrize("field", ["filed_at", "filed_by"])
def test_approved_ad_requires_submission_provenance(field):
    assert not can_send(_approved(**{field: ""}))


def test_filing_ledger_snapshots_inputs_and_outputs():
    ledger = FilingLedger()
    filing = _approved()
    ledger.record(filing)
    filing.status = "rejected"
    assert ledger.latest("ad-1").status == "approved"
    history = ledger.history("ad-1")
    history[0].status = "withdrawn"
    assert ledger.latest("ad-1").status == "approved"


def test_lapsed_and_prior_cycle_credentials_never_report_current():
    ma = credential_for("u", "attorney", "MA", "1", "2025-01-01")
    assert ma is not None
    ma.status = "lapsed"
    assert compliance_status(ma) == "expired"

    ny = credential_for("u", "attorney", "NY", "2", "2025-01-01")
    assert ny is not None
    record_hours(ny, CESession("2020-01-01", ny.required_hours, ny.required_ethics_hours))
    assert compliance_status(ny, now=datetime(2026, 1, 1).timestamp()) == "ce_deficient"


def test_leap_day_cycle_end_is_deterministic():
    credential = Credential(
        user_id="u",
        profession="attorney",
        state="NY",
        license_number="1",
        renewal_cycle_years=2,
        required_hours=1,
        required_ethics_hours=0,
        last_renewed="2024-02-29",
    )
    record_hours(credential, CESession("2024-03-01", 1))
    assert compliance_status(
        credential, now=datetime(2025, 1, 1).timestamp()
    ) == "current"


def test_unknown_security_tier_fails_closed(monkeypatch):
    profile = SimpleNamespace(
        data_security_tier="future-tier",
        data_security_citation="test",
    )
    monkeypatch.setattr(security_attestation, "get_legal_profile", lambda _state: profile)
    result = security_attestation.attest("NY", security_attestation.SecurityControls())
    assert not result.passed
    assert any(item.control == "data_security_tier" for item in result.findings)


def test_withdraw_requires_accountable_actor_and_reason():
    ledger = LegalHoldLedger()
    hold = ledger.issue(
        matter_id="m", issued_by="a", custodian="c", scope="all", reason="case"
    )
    with pytest.raises(LegalHoldError, match="withdrawn_by"):
        ledger.withdraw(hold_id=hold.hold_id, withdrawn_by=" ", reason="mistake")
    with pytest.raises(LegalHoldError, match="reason"):
        ledger.withdraw(hold_id=hold.hold_id, withdrawn_by="a", reason=" ")
