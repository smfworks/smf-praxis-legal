"""Conflict-of-interest checking across matters.

Party-name search across all matter workspaces (within an org), with a
pre-engagement conflict report. This crosses the workspace-isolation
boundary — it needs an org-level read index of party names (not matter
content), with break-glass controls. Sensitive — must not leak privileged
content across matters.

Design — respects the workspace-isolation boundary:
- The conflict index reads *only* the party-name surface fields on each
  Workspace (client_or_subject, title) — never memory items, artifacts,
  evidence, or any matter content. A conflict hit reveals that a name appears
  in another matter's party field; it does NOT reveal what that matter is
  about beyond its title + status.
- ``ConflictChecker`` takes a ``WorkspaceDirectory`` (the existing org-scoped
  directory) and runs name searches against ``list_for(organization_id)``.
- ``check(prospective_parties, organization_id)`` returns a ``ConflictReport``
  with matches ranked by similarity. Each match names the existing matter
  (workspace_id + title + status + client_or_subject) and the matching party.
- Break-glass: the caller must pass ``authorized_by`` (the attorney who
  authorized the conflict check). The check is auditable — every conflict
  query is logged with who ran it and what it returned.

This is a pre-engagement screening tool, not a continuous monitor. Run it
before opening a new matter to confirm no existing matter has a party that
creates a conflict.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Protocol

from hybridagent.workspaces import Workspace


class _DirectoryLike(Protocol):
    """Structural type matching WorkspaceDirectory.list_for."""
    def list_for(self, organization_id: str) -> list[Workspace]: ...


@dataclass(frozen=True)
class PartyName:
    """A party to check against existing matters."""
    name: str
    role: str = ""            # e.g. "client", "opposing party", "witness"
    is_organization: bool = False


@dataclass(frozen=True)
class ConflictHit:
    """A single conflict: a prospective party matches an existing matter's party."""
    prospective_party: str
    prospective_role: str
    matched_matter_id: str
    matched_matter_title: str
    matched_matter_status: str
    matched_party: str        # the client_or_subject on the existing matter
    similarity: float         # 0-1, how close the match is
    match_field: str          # "client_or_subject" or "title"


@dataclass
class ConflictReport:
    organization_id: str
    prospective_parties: tuple[PartyName, ...]
    hits: list[ConflictHit] = field(default_factory=list)
    checked_at: float = 0.0
    authorized_by: str = ""
    clean: bool = True         # True if no hits

    def summary(self) -> str:
        if self.clean:
            return (f"CLEAN: no conflicts found for "
                    f"{len(self.prospective_parties)} party/parties.")
        top = self.hits[0]
        return (f"CONFLICT: {len(self.hits)} potential conflict(s). "
                f"Closest: '{top.prospective_party}' ~ "
                f"'{top.matched_party}' (matter '{top.matched_matter_title}', "
                f"similarity {top.similarity:.2f})")


# ---------------------------------------------------------------------------
# Matching — fuzzy name comparison

def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", name.lower())).strip()


def _similarity(a: str, b: str) -> float:
    """Fuzzy similarity between two normalized names, 0-1."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # substring containment is a strong signal (e.g. "Acme Corp" in "Acme Corp LLC")
    if na in nb or nb in na:
        return 0.95
    return SequenceMatcher(None, na, nb).ratio()


SIMILARITY_THRESHOLD = 0.85   # above this = a conflict hit


# ---------------------------------------------------------------------------
# ConflictChecker

@dataclass
class ConflictChecker:
    """Pre-engagement conflict-of-interest screening across an org's matters.

    Reads only party-name surface fields (client_or_subject, title) from the
    WorkspaceDirectory — never matter content. Each check is auditable via
    the authorized_by field.
    """
    directory: _DirectoryLike
    threshold: float = SIMILARITY_THRESHOLD
    _audit_log: list[dict] = field(default_factory=list)

    def check(self, *, prospective_parties: list[PartyName],
              organization_id: str, authorized_by: str,
              now: float | None = None) -> ConflictReport:
        """Screen prospective parties against all existing matters in the org.

        ``authorized_by`` is the attorney who authorized the check (break-glass:
        every conflict query is logged with who ran it). Returns a report with
        hits ranked by similarity (highest first).
        """
        if not authorized_by.strip():
            raise ValueError("authorized_by is required (break-glass audit)")
        ts = now if now is not None else time.time()
        matters = self.directory.list_for(organization_id)
        hits: list[ConflictHit] = []
        for party in prospective_parties:
            if not party.name.strip():
                continue
            for matter in matters:
                # compare against the existing matter's client/subject + title
                for field_name, existing in (
                    ("client_or_subject", matter.client_or_subject),
                    ("title", matter.title),
                ):
                    if not existing:
                        continue
                    sim = _similarity(party.name, existing)
                    if sim >= self.threshold:
                        hits.append(ConflictHit(
                            prospective_party=party.name,
                            prospective_role=party.role,
                            matched_matter_id=matter.workspace_id,
                            matched_matter_title=matter.title,
                            matched_matter_status=matter.status,
                            matched_party=matter.client_or_subject,
                            similarity=sim,
                            match_field=field_name,
                        ))
        hits.sort(key=lambda h: h.similarity, reverse=True)
        report = ConflictReport(
            organization_id=organization_id,
            prospective_parties=tuple(prospective_parties),
            hits=hits, checked_at=ts, authorized_by=authorized_by,
            clean=not hits,
        )
        self._audit_log.append({
            "checked_at": ts, "organization_id": organization_id,
            "authorized_by": authorized_by,
            "prospective_parties": [p.name for p in prospective_parties],
            "hit_count": len(hits),
            "clean": report.clean,
        })
        return report

    def audit_log(self) -> list[dict]:
        """The audit trail of all conflict checks run through this checker."""
        return list(self._audit_log)


# ---------------------------------------------------------------------------
# Render — the conflict report for the attorney

def render_report(report: ConflictReport) -> str:
    """Human-readable conflict report for the pre-engagement decision."""
    lines = [
        f"Conflict-of-Interest Check — org {report.organization_id}",
        f"Authorized by: {report.authorized_by}",
        f"Checked at: {report.checked_at:.0f}",
        f"Prospective parties: {len(report.prospective_parties)}",
        report.summary(),
        "",
    ]
    if report.hits:
        lines.append(f"Potential conflicts ({len(report.hits)}):")
        for h in report.hits:
            lines.append(
                f"  [sim {h.similarity:.2f}] '{h.prospective_party}' "
                f"({h.prospective_role or '—'}) ~ {h.match_field} "
                f"'{h.matched_party}' on matter '{h.matched_matter_title}' "
                f"[{h.matched_matter_status}]"
            )
    else:
        lines.append("No potential conflicts detected.")
    return "\n".join(lines)