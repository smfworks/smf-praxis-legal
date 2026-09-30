"""Data-security attestation surface (MA 201 CMR 17.00 / NY SHIELD).

The existing ``compliance.py`` attests to *governance broker* decisions
(SEND/DESTRUCTIVE approvals). This module attests to a different thing:
*data-security controls state* — whether a WISP exists, whether encryption
is configured, whether employee training is current. MA 201 CMR 17.00 is the
strictest proactive data-security standard in the 13 states (WISP mandate +
encryption at rest/in transit + training + breach notification). NY SHIELD
adds an affirmative security-obligation (reasonable administrative, technical,
physical safeguards). The rest of the 13 are breach-notification-only.

Design:
- A ``SecurityControls`` dataclass captures declarative control state
  (WISP on file? encryption-at-rest configured? training current? etc.).
  The firm asserts this; Praxis doesn't verify it externally (no board or
  API verification).
- ``attest(state)`` returns a ``SecurityAttestation`` with findings + pass/fail
  against the active jurisdiction's requirements. Per-jurisdiction: MA demands
  the full WISP+encryption+training set; NY SHIELD demands reasonable
  safeguards; the rest demand only breach notification (minimal attestation).
- ``render(attestation)`` produces a human-readable evidence bundle a MA law
  firm can show its auditors.

This is an attestation *surface*, not a control *enforcement*. The controls
themselves (data classification, egress allowlist, redaction gate, sandbox
isolation) already live in ``data_policy.py`` / ``sandbox.py``. This module
evidences that they're in place + configured, per jurisdiction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from hybridagent.jurisdictions import get_legal_profile

Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass(frozen=True)
class SecurityControls:
    """Declarative data-security control state asserted by the firm.

    Praxis records this; the firm is responsible for the underlying truth
    (no board or API verification). A field set to False
    or empty is a gap that surfaces as a finding in the attestation.
    """
    wisp_on_file: bool = False             # Written Information Security Program exists
    wisp_last_reviewed: str = ""           # ISO date, e.g. "2026-06-01"
    encryption_at_rest: bool = False        # personal info encrypted at rest
    encryption_in_transit: bool = False     # personal info encrypted in transit (TLS)
    employee_training_current: bool = False
    training_last_completed: str = ""      # ISO date
    breach_notification_procedure: bool = False
    data_classification_enforced: bool = False  # Praxis data_policy Classification
    egress_allowlist_enforced: bool = False     # Praxis data_policy egress gate
    redaction_required_on_export: bool = False  # Praxis data_policy redaction gate
    sandbox_isolation_enabled: bool = False    # Praxis sandbox backend
    audit_trail_enabled: bool = False           # Praxis broker audit entries
    last_incident_test: str = ""            # ISO date of last breach-response drill


@dataclass
class SecurityFinding:
    severity: Severity
    control: str
    message: str
    requirement: str = ""     # the regulatory citation this maps to


@dataclass
class SecurityAttestation:
    jurisdiction: str
    tier: str                 # wisp_mandate | shield_obligation | breach_notification_only
    passed: bool
    findings: list[SecurityFinding] = field(default_factory=list)
    controls: SecurityControls | None = None
    profile_citation: str = ""

    def summary(self) -> str:
        if self.passed:
            return f"PASS: data-security controls satisfy {self.jurisdiction} requirements ({self.tier})."
        return f"FAIL: data-security controls do not satisfy {self.jurisdiction} requirements ({self.tier})."


# ---------------------------------------------------------------------------
# Per-tier requirement sets. Each returns the findings for missing controls.

def _check_wisp_mandate(c: SecurityControls) -> list[SecurityFinding]:
    """MA 201 CMR 17.00 — the strictest. WISP + encryption (rest+transit) +
    training + breach procedure + the Praxis controls that evidence it."""
    findings: list[SecurityFinding] = []
    if not c.wisp_on_file:
        findings.append(SecurityFinding("critical", "wisp_on_file",
            "No Written Information Security Program on file.",
            "201 CMR 17.00 §17.03(1) — WISP required"))
    if c.wisp_on_file and not c.wisp_last_reviewed:
        findings.append(SecurityFinding("medium", "wisp_last_reviewed",
            "WISP exists but last-review date is missing.",
            "201 CMR 17.00 — annual review expected"))
    if not c.encryption_at_rest:
        findings.append(SecurityFinding("critical", "encryption_at_rest",
            "Personal information not encrypted at rest.",
            "201 CMR 17.00 §17.04(5) — encryption of records at rest"))
    if not c.encryption_in_transit:
        findings.append(SecurityFinding("critical", "encryption_in_transit",
            "Personal information not encrypted in transit.",
            "201 CMR 17.00 §17.04(5) — encryption in transit"))
    if not c.employee_training_current:
        findings.append(SecurityFinding("high", "employee_training_current",
            "Employee security training not current.",
            "201 CMR 17.00 §17.03(2)(d) — employee training"))
    if not c.breach_notification_procedure:
        findings.append(SecurityFinding("high", "breach_notification_procedure",
            "No breach-notification procedure documented.",
            "201 CMR 17.00 §17.04(1) + M.G.L. c. 93H §3"))
    # Praxis controls that evidence the above (info-level if present, high if absent)
    for ctrl, label in (
        (c.data_classification_enforced, "data classification"),
        (c.egress_allowlist_enforced, "egress allowlist"),
        (c.redaction_required_on_export, "redaction on export"),
        (c.sandbox_isolation_enabled, "sandbox isolation"),
        (c.audit_trail_enabled, "audit trail"),
    ):
        if not ctrl:
            findings.append(SecurityFinding("medium", label,
                f"Praxis {label} not enabled — evidentiary gap for WISP compliance.",
                "201 CMR 17.00 — reasonable safeguards"))
    return findings


def _check_shield_obligation(c: SecurityControls) -> list[SecurityFinding]:
    """NY SHIELD Act — affirmative security-obligation: reasonable
    administrative, technical, physical safeguards. Less prescriptive than MA
    but requires documented safeguards."""
    findings: list[SecurityFinding] = []
    if not c.wisp_on_file and not c.data_classification_enforced:
        findings.append(SecurityFinding("high", "wisp_on_file",
            "No documented information security program and no data classification — "
            "SHIELD requires reasonable administrative safeguards.",
            "GBL §899-bb — reasonable administrative safeguards"))
    if not c.encryption_at_rest and not c.encryption_in_transit:
        findings.append(SecurityFinding("high", "encryption",
            "No encryption at rest or in transit — SHIELD requires reasonable technical safeguards.",
            "GBL §899-bb — reasonable technical safeguards"))
    if not c.breach_notification_procedure:
        findings.append(SecurityFinding("high", "breach_notification_procedure",
            "No breach-notification procedure — SHIELD Act breach notification required.",
            "GBL §899-aa — breach notification"))
    # Praxis controls evidence the safeguards (medium if absent, not critical)
    for ctrl, label in (
        (c.egress_allowlist_enforced, "egress allowlist"),
        (c.redaction_required_on_export, "redaction on export"),
        (c.sandbox_isolation_enabled, "sandbox isolation"),
        (c.audit_trail_enabled, "audit trail"),
    ):
        if not ctrl:
            findings.append(SecurityFinding("medium", label,
                f"Praxis {label} not enabled — evidentiary gap for SHIELD safeguards.",
                "GBL §899-bb — reasonable safeguards"))
    return findings


def _check_breach_notification_only(c: SecurityControls) -> list[SecurityFinding]:
    """Most states — breach notification required, no proactive security
    standard. Minimal attestation: just need a breach procedure."""
    findings: list[SecurityFinding] = []
    if not c.breach_notification_procedure:
        findings.append(SecurityFinding("high", "breach_notification_procedure",
            "No breach-notification procedure documented.",
            "State breach-notification statute (see jurisdiction profile)"))
    # Praxis controls are informational — good practice, not mandated
    present = sum([
        c.data_classification_enforced, c.egress_allowlist_enforced,
        c.redaction_required_on_export, c.sandbox_isolation_enabled,
        c.audit_trail_enabled,
    ])
    if present < 3:
        findings.append(SecurityFinding("info", "praxis_controls",
            f"Only {present}/5 Praxis data-security controls enabled. "
            "Not required by this jurisdiction but recommended as best practice.",
            ""))
    return findings


_CHECKERS = {
    "wisp_mandate": _check_wisp_mandate,
    "shield_obligation": _check_shield_obligation,
    "breach_notification_only": _check_breach_notification_only,
}


def attest(state: str, controls: SecurityControls) -> SecurityAttestation:
    """Build a per-jurisdiction data-security attestation.

    ``state`` is the two-letter code (loads the LegalProfile to determine the
    tier). Returns a SecurityAttestation with findings + pass/fail. If the
    state isn't in the registry, returns a minimal attestation with a finding.
    """
    profile = get_legal_profile(state)
    if profile is None:
        return SecurityAttestation(
            jurisdiction=state.upper(), tier="unknown", passed=False,
            findings=[SecurityFinding("critical", "jurisdiction",
                f"{state} is not in the 13-state registry.", "")],
            controls=controls,
        )
    tier = profile.data_security_tier
    checker = _CHECKERS.get(tier)
    if checker is None:
        return SecurityAttestation(
            jurisdiction=state.upper(), tier=tier, passed=False,
            findings=[SecurityFinding(
                "critical", "data_security_tier",
                f"Unsupported data-security tier: {tier!r}.",
                profile.data_security_citation,
            )],
            controls=controls,
            profile_citation=profile.data_security_citation,
        )
    findings = checker(controls)
    passed = not any(f.severity in ("critical", "high") for f in findings)
    return SecurityAttestation(
        jurisdiction=state.upper(), tier=tier, passed=passed,
        findings=findings, controls=controls,
        profile_citation=profile.data_security_citation,
    )


def render(att: SecurityAttestation) -> str:
    """Human-readable evidence bundle for auditors."""
    lines = [
        f"Data-Security Attestation — {att.jurisdiction}",
        f"Tier: {att.tier}",
        f"Citation: {att.profile_citation or '(see jurisdiction profile)'}",
        att.summary(),
        "",
    ]
    if not att.findings:
        lines.append("No findings — all required controls satisfied.")
    else:
        lines.append(f"Findings ({len(att.findings)}):")
        for f in att.findings:
            cite = f" [{f.requirement}]" if f.requirement else ""
            lines.append(f"  [{f.severity}] {f.control}: {f.message}{cite}")
    if att.controls:
        lines.append("")
        lines.append("Controls asserted:")
        c = att.controls
        lines.append(f"  wisp_on_file: {c.wisp_on_file} (reviewed {c.wisp_last_reviewed or '—'})")
        lines.append(f"  encryption_at_rest: {c.encryption_at_rest}")
        lines.append(f"  encryption_in_transit: {c.encryption_in_transit}")
        lines.append(f"  employee_training_current: {c.employee_training_current} "
                     f"(last {c.training_last_completed or '—'})")
        lines.append(f"  breach_notification_procedure: {c.breach_notification_procedure}")
        lines.append(f"  data_classification_enforced: {c.data_classification_enforced}")
        lines.append(f"  egress_allowlist_enforced: {c.egress_allowlist_enforced}")
        lines.append(f"  redaction_required_on_export: {c.redaction_required_on_export}")
        lines.append(f"  sandbox_isolation_enabled: {c.sandbox_isolation_enabled}")
        lines.append(f"  audit_trail_enabled: {c.audit_trail_enabled}")
    return "\n".join(lines)