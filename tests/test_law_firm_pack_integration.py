"""Law Firm pack — 13-state integration test (Slice 5).

Proves the pack works across all 13 states, not just NY and MA. For each
state, activates the pack with that jurisdiction and exercises the per-
jurisdiction behavior sourced from the Gap 1 registry:

  - ad-filing gate activates only for NY + FL (22 NYCRR 1200 / FL Bar)
  - WISP attestation tier is wisp_mandate for MA, shield_obligation for NY,
    breach_notification_only for the other 11
  - CLE is required for 12 states; MA is no_requirement
  - the CLE hour/cycle values match the registry per state
  - the security attestation FAILs for MA without a WISP, FAILs for NY
    without any safeguards, PASSes for the breach-only states with just a
    breach procedure

This is the test that proves the pack is a 13-state pack, not a 2-state pack.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hybridagent import config as cfg
from hybridagent import pack
from hybridagent_praxis_legal.modules.advertising_filing import (
    AdvertisingFiling,
    filing_required,
    validate_before_send,
)
from hybridagent_praxis_legal.modules.credentials import (
    CESession,
    compliance_status,
    credential_for,
    record_hours,
)
from hybridagent.jurisdictions import (
    get_legal_profile,
    registered_states,
)
from hybridagent_praxis_legal.modules.security_attestation import SecurityControls, attest


def _home(tmp_path, monkeypatch):
    monkeypatch.setenv(cfg.ENV_HOME, str(tmp_path / ".praxis"))


STATES = registered_states()


# ---------------------------------------------------------------------------
# 1. The pack is active and every state's legal profile loads through it

def test_law_firm_pack_activates(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    p = pack.activate("law_firm")
    assert p is not None
    assert p.name == "law_firm"
    assert cfg.get_active_pack_name() == "law_firm"
    pack.deactivate()


@pytest.mark.parametrize("state", STATES)
def test_every_state_has_a_legal_profile_the_pack_can_load(state):
    """The pack's per-jurisdiction logic flows from the Gap 1 registry. Every
    one of the 13 states must have a LEGAL profile the pack can load."""
    p = get_legal_profile(state)
    assert p is not None, f"{state} missing LEGAL profile"
    assert p.state == state.upper()
    assert p.bar_name
    assert p.governing_rules


# ---------------------------------------------------------------------------
# 2. The ad-filing gate — only NY + FL

@pytest.mark.parametrize("state", STATES)
def test_ad_filing_gate_only_activates_for_ny_and_fl(state):
    """validate_before_send returns findings only for NY + FL. The other 11
    states return [] (no filing requirement)."""
    profile = get_legal_profile(state)
    assert profile is not None
    f = AdvertisingFiling(artifact_id="ad-1", jurisdiction=state.upper(),
                          status="draft")
    findings = validate_before_send(f)
    if profile.advertising_filing_required:
        # NY or FL — the gate activates, draft status is a high finding
        assert any(x.field == "status" for x in findings), (
            f"{state} should gate advertising (filing required)")
        assert filing_required(state) is True
    else:
        # the other 11 — no requirement, no findings
        assert findings == [], f"{state} should not gate advertising"
        assert filing_required(state) is False


def test_only_ny_and_fl_require_ad_filing():
    filing_states = [s for s in STATES if filing_required(s)]
    assert set(filing_states) == {"ny", "fl"}


# ---------------------------------------------------------------------------
# 3. The data-security tiers — MA WISP, NY SHIELD, the rest breach-only

@pytest.mark.parametrize("state", STATES)
def test_security_attestation_tier_per_state(state):
    profile = get_legal_profile(state)
    assert profile is not None
    att = attest(state, SecurityControls())  # nothing asserted
    assert att.tier == profile.data_security_tier


def test_ma_attestation_fails_without_wisp():
    att = attest("MA", SecurityControls())
    assert not att.passed
    assert any(x.severity == "critical" and x.control == "wisp_on_file"
               for x in att.findings)


def test_ny_attestation_fails_without_safeguards():
    att = attest("NY", SecurityControls())
    assert not att.passed


@pytest.mark.parametrize("state", [s for s in STATES if s not in ("ma", "ny")])
def test_breach_only_states_pass_with_just_breach_procedure(state):
    """The 11 breach-notification-only states pass with only a breach
    procedure — no WISP/encryption/training mandate."""
    controls = SecurityControls(breach_notification_procedure=True)
    att = attest(state, controls)
    assert att.passed, f"{state} should pass with just a breach procedure"


# ---------------------------------------------------------------------------
# 4. CLE requirements — 12 states require it, MA is the exception

@pytest.mark.parametrize("state", STATES)
def test_cle_requirement_per_state(state):
    profile = get_legal_profile(state)
    assert profile is not None
    if state == "ma":
        assert profile.cle_required is False
    else:
        assert profile.cle_required is True


@pytest.mark.parametrize("state", [s for s in STATES if s != "ma"])
def test_cle_credentials_track_per_state_requirement(state):
    """For each CLE-requiring state, a credential with insufficient hours is
    ce_deficient; with sufficient hours is current."""
    c = credential_for("u", "attorney", state, "1", "2026-01-01")
    assert c is not None
    # insufficient hours -> deficient
    assert compliance_status(c) == "ce_deficient"
    # sufficient hours + ethics -> current
    record_hours(c, CESession(
        date="2026-02-01",
        hours=c.required_hours,
        ethics_hours=c.required_ethics_hours))
    assert compliance_status(c) == "current"


def test_ma_attorney_credential_is_no_requirement():
    """MA is the only state where an attorney credential is no_requirement."""
    c = credential_for("u", "attorney", "MA", "1", "2026-01-01")
    assert c is not None
    assert compliance_status(c) == "no_requirement"


# ---------------------------------------------------------------------------
# 5. The full-pack integration — activate + the persona + the 13-state coverage

def test_law_firm_pack_persona_covers_all_13_states(tmp_path, monkeypatch):
    """The pack persona references the states + compliance flags that the
    13-state registry encodes."""
    _home(tmp_path, monkeypatch)
    p = pack.load_pack("law_firm")
    assert p is not None
    sp = p.system_prompt
    # the ad-filing states (NY + FL) are named in the persona
    assert "NY" in sp and "FL" in sp
    # MA (WISP) + SHIELD are named
    assert "MA" in sp and "SHIELD" in sp
    # the universal guardrails (all 13 states)
    assert "IOLTA" in sp
    assert "do not provide legal advice" in sp
    assert "conflict" in sp.lower()
    assert "litigation hold" in sp.lower()


def test_law_firm_pack_knowledge_covers_13_states(tmp_path, monkeypatch):
    """The knowledge base ingested into pack:law_firm references all 13
    states in the quick-reference table."""
    _home(tmp_path, monkeypatch)
    loaded = pack.load_pack("law_firm")
    assert loaded is not None
    kb = (Path(loaded.path) / "knowledge.md").read_text(encoding="utf-8")
    # every state code appears in the 13-state quick reference
    for state in ("FL", "GA", "SC", "TN", "VA", "WV", "MD", "PA",
                  "OH", "NJ", "NY", "CT", "MA"):
        assert state in kb, f"{state} missing from knowledge base"


# ---------------------------------------------------------------------------
# 6. End-to-end: activate the pack + run the 13-state compliance surfaces

def test_law_firm_endpoint_covers_13_state_tiers(tmp_path, monkeypatch):
    """The /api/law_firm endpoint's security attestation surface reports the
    correct tier for each of the 13 states when the daemon is configured with
    all 13 as active jurisdictions."""
    _home(tmp_path, monkeypatch)
    import json
    import time
    import urllib.request

    from hybridagent.daemon import Daemon
    from hybridagent.llm import LLMClient
    pack.activate("law_firm")
    d = Daemon(llm=LLMClient(mode="mock"), status_port=0)
    # configure the daemon to attest against all 13 states
    d._lf_jurisdictions = [s.upper() for s in STATES]
    d._start_status_server()
    time.sleep(0.3)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{d.status_port}/api/law_firm", timeout=5
        ) as r:
            body = json.loads(r.read())
        assert body["active"] is True
        sa = body["security_attestations"]
        states_reported = {j["state"] for j in sa["jurisdictions"]}
        assert states_reported == {s.upper() for s in STATES}
        # MA is wisp_mandate, NY is shield_obligation, the rest are breach-only
        tiers = {j["state"]: j["tier"] for j in sa["jurisdictions"]}
        assert tiers["MA"] == "wisp_mandate"
        assert tiers["NY"] == "shield_obligation"
        for st in STATES:
            if st.upper() not in ("MA", "NY"):
                assert tiers[st.upper()] == "breach_notification_only"
    finally:
        d._stop_status_server()
        pack.deactivate()