"""Matter-wide legal-hold workflow (custodian acknowledgment + release).

The existing ``data_policy.py`` has the per-record ``legal_hold=True`` primitive
(passed to ``disposition()`` → returns "hold" → ``authorize_delete()`` raises).
And ``WorkspaceDirectory.set_hold`` sets the workspace-level hold flag. What
this module adds, covering litigation-hold practice across the 13 states, is
the *workflow* on top:

  * a matter-wide hold *issuance* (record who issued it, why, scope, custodian);
  * a custodian-*acknowledgment* step (the custodian confirms they've preserved);
  * a *release* with audit (who released, when, why); and
  * a ledger of all holds per matter so a firm can evidence compliance.

This module provides that workflow. It does not replace the per-record
primitive or the workspace flag — it wraps them with the issuance + ack +
release record-keeping that litigation-hold defensibility requires.

Design:
- ``LegalHold`` — the hold record (hold_id, matter_id, issued_by, custodian,
  scope, reason, issued_at, acknowledged_at, released_at, released_by,
  release_reason, status). Statuses: issued → acknowledged → released
  (or withdrawn if rescinded before ack).
- ``LegalHoldLedger`` — append-only store of holds keyed by matter_id.
  ``issue`` / ``acknowledge`` / ``release`` transition the state with audit.
- ``matter_under_hold(matter_id)`` — True if any active (unreleased) hold
  exists. Downstream delete/retention paths call this to gate disposition.
- ``render_matter_summary(matter_id)`` — the compliance report for auditors.

Integration with existing primitives (not a replacement):
- The firm still sets the workspace-level flag via WorkspaceDirectory.set_hold
  (the workspace record itself is held).
- The data_policy.disposition(legal_hold=True) path still blocks per-record
  deletes when a record is under hold.
- This module tells you *whether* a matter is under hold (the ledger is the
  system of record for the workflow) so callers know to pass legal_hold=True.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

HoldStatus = Literal["issued", "acknowledged", "released", "withdrawn"]


@dataclass
class LegalHold:
    """A single matter-wide legal hold."""
    hold_id: str
    matter_id: str               # workspace_id of the matter
    issued_by: str               # attorney id/name who issued
    custodian: str              # who must preserve (often the same or a records custodian)
    scope: str                   # what's in scope, e.g. "all emails + evidence re: Smith v Jones"
    reason: str                  # the litigation/investigation trigger
    issued_at: float
    acknowledged_at: float = 0.0       # 0 = not yet acknowledged
    acknowledged_by: str = ""
    released_at: float = 0.0
    released_by: str = ""
    release_reason: str = ""
    status: HoldStatus = "issued"
    notes: str = ""

    @property
    def is_active(self) -> bool:
        """A hold is active when issued or acknowledged (not released/withdrawn)."""
        return self.status in ("issued", "acknowledged")

    @property
    def is_acknowledged(self) -> bool:
        return self.status == "acknowledged"


class LegalHoldError(ValueError):
    """Raised on illegal hold state transitions or missing required fields."""


@dataclass
class LegalHoldLedger:
    """Append-only store of legal holds per matter.

    Each matter can have multiple holds over time (issue → ack → release,
    then a new hold for a different matter). The ledger is the system of
    record for the hold workflow. ``matter_under_hold`` tells callers whether
    to pass legal_hold=True to the per-record disposition path.
    """
    _by_matter: dict[str, list[LegalHold]] = field(default_factory=dict)

    def issue(self, *, matter_id: str, issued_by: str, custodian: str,
              scope: str, reason: str, notes: str = "",
              now: float | None = None) -> LegalHold:
        """Issue a new matter-wide hold. Returns the hold record.

        Raises if required fields are empty or if there's already an active
        hold on this matter (don't stack — release the old one first).
        """
        matter_id = matter_id.strip()
        issued_by = issued_by.strip()
        custodian = custodian.strip()
        scope = scope.strip()
        reason = reason.strip()
        if not matter_id:
            raise LegalHoldError("matter_id is required")
        if not issued_by:
            raise LegalHoldError("issued_by is required")
        if not custodian:
            raise LegalHoldError("custodian is required")
        if not scope:
            raise LegalHoldError("scope is required")
        if not reason:
            raise LegalHoldError("reason is required (the litigation trigger)")
        if self.matter_under_hold(matter_id):
            raise LegalHoldError(
                f"matter {matter_id} already has an active hold — release it first")
        ts = now if now is not None else time.time()
        hold = LegalHold(
            hold_id=f"hold-{uuid.uuid4().hex[:12]}",
            matter_id=matter_id, issued_by=issued_by, custodian=custodian,
            scope=scope, reason=reason, issued_at=ts, notes=notes,
            status="issued",
        )
        self._by_matter.setdefault(matter_id, []).append(hold)
        return hold

    def acknowledge(self, *, hold_id: str, acknowledged_by: str,
                    now: float | None = None) -> LegalHold:
        """Custodian confirms they've preserved. Transitions issued → acknowledged."""
        acknowledged_by = acknowledged_by.strip()
        if not acknowledged_by:
            raise LegalHoldError("acknowledged_by is required")
        hold = self._find(hold_id)
        if hold is None:
            raise LegalHoldError(f"hold {hold_id} not found")
        if hold.status != "issued":
            raise LegalHoldError(
                f"hold {hold_id} is {hold.status}, cannot acknowledge")
        ts = now if now is not None else time.time()
        hold.acknowledged_at = ts
        hold.acknowledged_by = acknowledged_by
        hold.status = "acknowledged"
        return hold

    def release(self, *, hold_id: str, released_by: str, release_reason: str,
                now: float | None = None) -> LegalHold:
        """Release the hold. Transitions issued/acknowledged → released."""
        released_by = released_by.strip()
        release_reason = release_reason.strip()
        if not released_by:
            raise LegalHoldError("released_by is required")
        if not release_reason:
            raise LegalHoldError("release_reason is required")
        hold = self._find(hold_id)
        if hold is None:
            raise LegalHoldError(f"hold {hold_id} not found")
        if hold.status not in ("issued", "acknowledged"):
            raise LegalHoldError(
                f"hold {hold_id} is {hold.status}, cannot release")
        ts = now if now is not None else time.time()
        hold.released_at = ts
        hold.released_by = released_by
        hold.release_reason = release_reason
        hold.status = "released"
        return hold

    def withdraw(self, *, hold_id: str, withdrawn_by: str,
                 reason: str, now: float | None = None) -> LegalHold:
        """Rescind a hold before acknowledgment (e.g. issued in error)."""
        if not withdrawn_by.strip():
            raise LegalHoldError("withdrawn_by is required")
        if not reason.strip():
            raise LegalHoldError("reason is required")
        hold = self._find(hold_id)
        if hold is None:
            raise LegalHoldError(f"hold {hold_id} not found")
        if hold.status != "issued":
            raise LegalHoldError(
                f"hold {hold_id} is {hold.status}, cannot withdraw")
        ts = now if now is not None else time.time()
        hold.released_at = ts
        hold.released_by = withdrawn_by
        hold.release_reason = f"WITHDRAWN: {reason}"
        hold.status = "withdrawn"
        return hold

    # ----------------------------------------------------------- queries

    def matter_under_hold(self, matter_id: str) -> bool:
        """True if any active (unreleased) hold exists on this matter.
        Callers use this to decide whether to pass legal_hold=True to the
        per-record disposition path."""
        return any(h.is_active for h in self._by_matter.get(matter_id, []))

    def active_holds(self, matter_id: str) -> list[LegalHold]:
        return [h for h in self._by_matter.get(matter_id, []) if h.is_active]

    def history(self, matter_id: str) -> list[LegalHold]:
        return list(self._by_matter.get(matter_id, []))

    def latest(self, matter_id: str) -> LegalHold | None:
        records = self._by_matter.get(matter_id)
        return records[-1] if records else None

    def get(self, hold_id: str) -> LegalHold | None:
        return self._find(hold_id)

    def all_holds(self) -> list[LegalHold]:
        out: list[LegalHold] = []
        for records in self._by_matter.values():
            out.extend(records)
        return out

    # ----------------------------------------------------------- internal

    def _find(self, hold_id: str) -> LegalHold | None:
        for records in self._by_matter.values():
            for h in records:
                if h.hold_id == hold_id:
                    return h
        return None


# ---------------------------------------------------------------------------
# Render — the compliance summary for a matter

def render_matter_summary(matter_id: str, ledger: LegalHoldLedger) -> str:
    """Human-readable hold-compliance report for a matter."""
    holds = ledger.history(matter_id)
    active = ledger.active_holds(matter_id)
    lines = [
        f"Legal-Hold Summary — matter {matter_id}",
        f"Total holds on record: {len(holds)}",
        f"Active holds: {len(active)}",
        "",
    ]
    if not holds:
        lines.append("No holds on record.")
        return "\n".join(lines)
    lines.append("Holds:")
    for h in holds:
        state = h.status.upper()
        ack = f" ack={h.acknowledged_at:.0f}" if h.acknowledged_at else " ack=pending"
        rel = f" released={h.released_at:.0f}" if h.released_at else ""
        lines.append(f"  [{state}] {h.hold_id}: scope='{h.scope}' "
                     f"reason='{h.reason}' issued={h.issued_at:.0f}{ack}{rel}")
        if h.is_acknowledged:
            lines.append(f"    acknowledged_by={h.acknowledged_by}")
    return "\n".join(lines)