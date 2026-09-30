"""Privilege log + expert-witness disclosure templates.

Two artifact templates for law-firm discovery work:
  privilege log — the document-by-document privilege claim (attorney-
    client, work-product, etc.) required during discovery.
  expert-witness disclosure — the federal Rule 26(a)(2) / state-
    equivalent disclosure (qualifications, prior testimony, compensation,
    basis for opinion), per-jurisdiction format.

Both are standalone generators (like the advertising-filing tracker) —
they reference artifacts by id and don't touch the canonical IR. The firm
fills in the content; the templates produce the standard format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from hybridagent.jurisdictions import get_legal_profile

PrivilegeBasis = Literal[
    "attorney_client",        # RPC 1.6 confidentiality / attorney-client privilege
    "work_product",           # work-product doctrine
    "attorney_work_product",   # Hickman v. Taylor / state equivalents
    "joint_defense",
    "common_interest",
    "other",
]


# ---------------------------------------------------------------------------
# Privilege log

@dataclass(frozen=True)
class PrivilegeEntry:
    """One row in a privilege log: a withheld document + the privilege claim."""
    document_id: str           # Bates number or artifact id
    date: str                   # document date
    author: str
    recipients: str             # comma-separated
    document_type: str          # "email", "memo", "report", etc.
    description: str            # short description of the document
    privilege_basis: PrivilegeBasis
    privilege_basis_detail: str  # the specific reasoning
    redacted: bool = False
    redaction_note: str = ""    # what was redacted and why


@dataclass
class PrivilegeLog:
    """A privilege log for a matter — the list of withheld documents + claims."""
    matter_id: str
    producing_party: str        # the firm/client producing the log
    receiving_party: str        # the opposing party
    entries: list[PrivilegeEntry] = field(default_factory=list)
    prepared_by: str = ""
    prepared_at: str = ""
    notes: str = ""

    def add(self, entry: PrivilegeEntry) -> PrivilegeLog:
        self.entries.append(entry)
        return self

    @property
    def basis_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.privilege_basis] = counts.get(e.privilege_basis, 0) + 1
        return counts


_BASIS_LABELS = {
    "attorney_client": "Attorney-Client Privilege",
    "work_product": "Work-Product Doctrine",
    "attorney_work_product": "Attorney Work-Product (Hickman v. Taylor)",
    "joint_defense": "Joint Defense Privilege",
    "common_interest": "Common Interest Privilege",
    "other": "Other Privilege (see detail)",
}


def render_privilege_log(log: PrivilegeLog) -> str:
    """Produce the standard privilege-log format for discovery."""
    lines = [
        f"PRIVILEGE LOG — matter {log.matter_id}",
        f"Producing party: {log.producing_party}",
        f"Receiving party: {log.receiving_party}",
        f"Prepared by: {log.prepared_by or '—'} at {log.prepared_at or '—'}",
        f"Total withheld documents: {len(log.entries)}",
        "",
        "Basis summary:",
    ]
    for basis, count in sorted(log.basis_counts.items()):
        label = _BASIS_LABELS.get(basis, basis)
        lines.append(f"  {label}: {count}")
    lines.append("")
    lines.append("Log entries:")
    lines.append(f"  {'BATES/ID':<20} {'DATE':<12} {'AUTHOR':<18} {'TYPE':<10} "
                 f"{'BASIS':<24} {'DESCRIPTION'}")
    for e in log.entries:
        label = _BASIS_LABELS.get(e.privilege_basis, e.privilege_basis)[:24]
        lines.append(
            f"  {e.document_id[:20]:<20} {e.date[:12]:<12} {e.author[:18]:<18} "
            f"{e.document_type[:10]:<10} {label:<24} {e.description}")
        if e.redacted:
            lines.append(f"    redacted: {e.redaction_note}")
        if e.privilege_basis_detail:
            lines.append(f"    basis detail: {e.privilege_basis_detail}")
    if log.notes:
        lines.append("")
        lines.append(f"Notes: {log.notes}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Expert-witness disclosure (Rule 26(a)(2) / state equivalent)

@dataclass(frozen=True)
class PriorTestimony:
    """A prior expert testimony engagement for the disclosure list."""
    case_name: str
    court: str                # e.g. "S.D.N.Y." or "PA Court of Common Pleas"
    year: str
    role: str = ""            # "testifying expert", "consulting only", etc.


@dataclass
class ExpertDisclosure:
    """The Rule 26(a)(2) / state-equivalent expert-witness disclosure."""
    matter_id: str
    expert_name: str
    expert_qualifications: str        # education, licenses, experience
    subject_matter: str               # what the expert will testify about
    basis_for_opinion: str             # the facts/data/ methodology
    compensation: str                  # billing rate / arrangement
    prior_testimony: list[PriorTestimony] = field(default_factory=list)
    authored_documents: list[str] = field(default_factory=list)  # artifact ids
    prepared_by: str = ""
    jurisdiction: str = ""            # two-letter code (determines format variant)
    notes: str = ""


def render_expert_disclosure(disclosure: ExpertDisclosure) -> str:
    """Produce the expert-witness disclosure, per-jurisdiction format.

    Federal Rule 26(a)(2)(B) requires: qualifications, subject matter, basis
    for opinion, exhibits, compensation, prior testimony list. State variants
    are largely the same; the jurisdiction field surfaces which rules apply.
    """
    lines = [
        f"EXPERT-WITNESS DISCLOSURE — matter {disclosure.matter_id}",
        f"Expert: {disclosure.expert_name}",
    ]
    if disclosure.jurisdiction:
        profile = get_legal_profile(disclosure.jurisdiction)
        rules = profile.governing_rules if profile else ""
        lines.append(f"Jurisdiction: {disclosure.jurisdiction} ({rules or '—'})")
    lines += [
        "",
        "1. Qualifications:",
        f"   {disclosure.expert_qualifications}",
        "",
        "2. Subject matter of testimony:",
        f"   {disclosure.subject_matter}",
        "",
        "3. Basis for opinion (facts/data considered):",
        f"   {disclosure.basis_for_opinion}",
        "",
        "4. Compensation:",
        f"   {disclosure.compensation}",
        "",
        "5. Prior testimony list:",
    ]
    if disclosure.prior_testimony:
        for t in disclosure.prior_testimony:
            lines.append(f"   - {t.case_name} ({t.court}, {t.year}) — {t.role or 'testifying'}")
    else:
        lines.append("   (none in the past four years)")
    if disclosure.authored_documents:
        lines.append("")
        lines.append("6. Exhibits / authored documents:")
        for doc_id in disclosure.authored_documents:
            lines.append(f"   - {doc_id}")
    if disclosure.prepared_by:
        lines.append("")
        lines.append(f"Prepared by: {disclosure.prepared_by}")
    if disclosure.notes:
        lines.append(f"Notes: {disclosure.notes}")
    return "\n".join(lines)