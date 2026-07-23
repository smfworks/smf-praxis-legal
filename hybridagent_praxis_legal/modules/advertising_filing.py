"""Attorney-advertising filing workflow (Gap 2 — NY 22 NYCRR 1200, + FL).

NY and FL are the only two states in the 13 that require attorney-advertising
*filing* — NY with the Appellate Division's Attorney Advertising Registration
Unit (22 NYCRR Part 1200, the strictest in the nation), FL with The Florida
Bar. The other 11 states don't require filing.

Praxis already routes ad copy as DRAFT → attorney approval before SEND (the
governance-broker SEND-risk hold). That's the right *governance* posture. This
module adds the *filing-tracking* workflow: record the filing date, filing/
approval number, disclaimer inclusion, and label — so a NY or FL law firm can
evidence compliance. Per the gap analysis: "an advertising-filing tracker on
top of the artifacts module... require filing-metadata fields before SEND
approval. Configurable per jurisdiction."

Design (standalone, doesn't touch the artifacts canonical IR):
- ``AdvertisingFiling`` — the filing record (artifact_id, jurisdiction, status,
  filed_at, filing_number, disclaimers_present, label_present, filed_by,
  authority, notes). Statuses: draft → filed → approved | rejected | withdrawn.
- ``filing_required(state)`` — consults the Gap 1 registry
  (LegalProfile.advertising_filing_required). Only NY + FL return True.
- ``validate_before_send(filing)`` — for NY/FL, requires label + disclaimers +
  a non-empty filing number before the SEND approval can proceed. Returns a
  list of missing-required findings (empty = OK to send).
- ``FilingLedger`` — append-only store of filing records keyed by artifact_id,
  with lookup + history. The custodian-acknowledgment analog for ad filings.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

from hybridagent.jurisdictions import get_legal_profile

FilingStatus = Literal["draft", "filed", "approved", "rejected", "withdrawn"]
Severity = Literal["critical", "high", "medium", "low", "info"]


@dataclass
class AdvertisingFiling:
    """Filing record for a single advertising artifact in one jurisdiction."""
    artifact_id: str               # reference to the artifact (no canonical-IR touch)
    jurisdiction: str              # two-letter code, e.g. "NY"
    status: FilingStatus = "draft"
    filed_at: str = ""             # ISO date the filing was submitted
    filing_number: str = ""        # the authority's filing/approval number
    filed_by: str = ""             # who filed (attorney id/name)
    authority: str = ""            # where filed, e.g. "NY Appellate Division"
    disclaimers_present: bool = False  # "Prior results do not guarantee..." etc.
    label_present: bool = False       # "Attorney Advertising" label on the piece
    content_summary: str = ""      # short description of what was filed
    notes: str = ""

    @property
    def is_complete(self) -> bool:
        """A filing is complete when filed + has a filing number (approved or
        at least filed with an authority-issued number)."""
        return (
            self.status in ("filed", "approved")
            and bool(self.filing_number.strip())
            and bool(self.filed_at.strip())
            and bool(self.filed_by.strip())
            and bool(self.authority.strip())
        )


@dataclass
class FilingFinding:
    severity: Severity
    field: str
    message: str
    requirement: str = ""


# ---------------------------------------------------------------------------
# Filing-required lookup — delegates to the Gap 1 registry

def filing_required(state: str) -> bool:
    """True if the jurisdiction requires attorney-advertising filing.
    Only NY (22 NYCRR 1200) and FL in the 13. The other 11 don't."""
    profile = get_legal_profile(state)
    if profile is None:
        return False
    return profile.advertising_filing_required


def filing_authority(state: str) -> str:
    """Where to file in this jurisdiction, or '' if not required."""
    profile = get_legal_profile(state)
    if profile is None or not profile.advertising_filing_required:
        return ""
    return profile.advertising_filing_authority


def filing_citation(state: str) -> str:
    """The regulatory citation for the filing requirement, or ''."""
    profile = get_legal_profile(state)
    if profile is None or not profile.advertising_filing_required:
        return ""
    return profile.advertising_filing_citation


# ---------------------------------------------------------------------------
# Validation — the SEND gate for advertising in NY/FL

def validate_before_send(filing: AdvertisingFiling) -> list[FilingFinding]:
    """Validate the filing record before the SEND approval can proceed.

    For NY/FL: the label + disclaimers + a filed status with a filing number
    are required. For non-filing states: returns [] (no filing requirement).

    Returns a list of findings; empty list = OK to send.
    """
    profile = get_legal_profile(filing.jurisdiction)
    if profile is None:
        return [FilingFinding(
            "critical", "jurisdiction",
            f"Unsupported jurisdiction: {filing.jurisdiction!r}.", "",
        )]
    if not profile.advertising_filing_required:
        return []  # no filing requirement in this jurisdiction
    findings: list[FilingFinding] = []
    citation = filing_citation(filing.jurisdiction)
    if not filing.label_present:
        findings.append(FilingFinding(
            "critical", "label_present",
            "Advertising piece is missing the required 'Attorney Advertising' label.",
            citation))
    if not filing.disclaimers_present:
        findings.append(FilingFinding(
            "critical", "disclaimers_present",
            "Advertising piece is missing the mandatory disclaimers "
            "('Prior results do not guarantee a similar outcome').",
            citation))
    if filing.status not in {"draft", "filed", "approved", "rejected", "withdrawn"}:
        findings.append(FilingFinding(
            "critical", "status", f"Unknown filing status: {filing.status!r}.", citation,
        ))
    elif filing.status == "draft":
        findings.append(FilingFinding(
            "high", "status",
            "Filing status is 'draft' — must be filed with the authority before SEND.",
            citation))
    elif filing.status in ("filed", "approved") and not filing.filing_number:
        findings.append(FilingFinding(
            "high", "filing_number",
            "Filing was submitted but no filing/approval number recorded — "
            "cannot evidence compliance.",
            citation))
    elif filing.status == "rejected":
        findings.append(FilingFinding(
            "critical", "status",
            "Filing was rejected by the authority — cannot send.",
            citation))
    elif filing.status == "withdrawn":
        findings.append(FilingFinding(
            "high", "status",
            "Filing was withdrawn — cannot send without a re-file.",
            citation))
    if filing.status in {"filed", "approved"} and not filing.filed_at.strip():
        findings.append(FilingFinding(
            "high", "filed_at", "Filing date is required to evidence submission.", citation,
        ))
    if filing.status in {"filed", "approved"} and not filing.filed_by.strip():
        findings.append(FilingFinding(
            "high", "filed_by", "Filer identity is required to evidence submission.", citation,
        ))
    if not filing.authority:
        findings.append(FilingFinding(
            "medium", "authority",
            "Filing authority not recorded.",
            citation))
    return findings


def can_send(filing: AdvertisingFiling) -> bool:
    """True if validate_before_send returns no critical/high findings."""
    return not any(f.severity in ("critical", "high")
                   for f in validate_before_send(filing))


# ---------------------------------------------------------------------------
# FilingLedger — append-only record of filings per artifact

@dataclass
class FilingLedger:
    """Append-only store of advertising-filing records, keyed by artifact_id.

    Each artifact can have a sequence of filing records (draft → filed →
    approved/rejected/withdrawn). The latest record is the current status.
    Kept in-memory; a real deployment persists this alongside the artifact.
    """
    _by_artifact: dict[str, list[AdvertisingFiling]] = field(default_factory=dict)

    def record(self, filing: AdvertisingFiling) -> None:
        if not filing.artifact_id.strip():
            raise ValueError("artifact_id is required")
        self._by_artifact.setdefault(filing.artifact_id, []).append(deepcopy(filing))

    def latest(self, artifact_id: str) -> AdvertisingFiling | None:
        records = self._by_artifact.get(artifact_id)
        return deepcopy(records[-1]) if records else None

    def history(self, artifact_id: str) -> list[AdvertisingFiling]:
        return deepcopy(self._by_artifact.get(artifact_id, []))

    def all_filings(self) -> list[AdvertisingFiling]:
        out: list[AdvertisingFiling] = []
        for records in self._by_artifact.values():
            out.extend(records)
        return deepcopy(out)

    def filings_for_jurisdiction(self, state: str) -> list[AdvertisingFiling]:
        return [f for f in self.all_filings() if f.jurisdiction == state.upper()]

    def compliant_filings(self, state: str) -> list[AdvertisingFiling]:
        """Filings in this jurisdiction that pass validate_before_send
        (i.e. evidence compliance)."""
        return [f for f in self.filings_for_jurisdiction(state)
                if can_send(f)]


# ---------------------------------------------------------------------------
# Render — the compliance report for a jurisdiction's filings

def render_jurisdiction_summary(state: str, ledger: FilingLedger) -> str:
    """Human-readable summary of a jurisdiction's filing-compliance status."""
    profile = get_legal_profile(state)
    if profile is None or not profile.advertising_filing_required:
        return (f"{state.upper()}: attorney-advertising filing is NOT required "
                f"in this jurisdiction.")
    filings = ledger.filings_for_jurisdiction(state)
    compliant = ledger.compliant_filings(state)
    lines = [
        f"Attorney-Advertising Filing Summary — {state.upper()}",
        f"Authority: {profile.advertising_filing_authority}",
        f"Citation: {profile.advertising_filing_citation}",
        f"Total filings on record: {len(filings)}",
        f"Compliant (pass validate_before_send): {len(compliant)}",
        "",
    ]
    if not filings:
        lines.append("No filings on record.")
    else:
        lines.append("Filings:")
        for f in filings:
            ok = "PASS" if can_send(f) else "FAIL"
            lines.append(f"  [{ok}] {f.artifact_id}: status={f.status} "
                         f"filed_at={f.filed_at or '—'} "
                         f"filing_number={f.filing_number or '—'}")
    return "\n".join(lines)