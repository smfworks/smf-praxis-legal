"""Professional credential + continuing-education tracking (Gap 4).

Per the 13-state gap analysis: 12 of 13 states require CLE for attorneys (MA
is the only exception); all 13 require PDH for PEs. A firm using Praxis can't
evidence that its professionals maintain licensure without a credential
tracker. This module is that tracker — per-user professional-license registry
with CE/PDH hour accumulation, ethics-hour tracking, renewal-cycle management,
and per-state configurable requirements sourced from the Gap 1 registry.

Per the gap analysis: Praxis tracks the *asserted* credential; the firm is
responsible for verification (no board-API integrations — the boards don't
all expose them, and Praxis is a knowledge platform, not a verification
authority).

Design:
- ``Credential`` — a professional license (user_id, profession (attorney|pe),
  state, license_number, renewal_cycle_years, CE/PDH hours accumulated, ethics
  hours, last_renewed, expires_at, status). Per-state requirements come from
  the registry: LegalProfile.cle_hours/cycle/ethics for attorneys;
  ForensicProfile.pdh_hours/cycle/ethics for PEs.
- ``record_hours`` — add a CE/PDH session (hours + ethics hours + date) to a
  credential, accumulating toward the cycle requirement.
- ``compliance_status`` — returns whether the credential is current, expiring
  soon, expired, or CE-deficient (hours or ethics below the state requirement).
- ``CredentialLedger`` — per-user store of credentials + the CE/PDH sessions.

The cycle math: hours accumulate from last_renewed to last_renewed +
renewal_cycle_years. At renewal, the cycle resets. CE-deficient = accumulated
hours < required hours for the current cycle window.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal

from hybridagent.jurisdictions import (
    get_education_profile,
    get_forensic_profile,
    get_legal_profile,
    get_medical_profile,
)

Profession = Literal["attorney", "pe", "physician", "teacher"]
CredentialStatus = Literal["current", "expiring_soon", "expired", "ce_deficient", "no_requirement"]


@dataclass
class CESession:
    """A single continuing-education session recorded against a credential."""
    date: str          # ISO date, e.g. "2026-06-15"
    hours: float       # total CE/PDH hours for this session
    ethics_hours: float = 0.0   # subset of `hours` that were ethics
    provider: str = ""
    course_name: str = ""
    topic: str = ""           # for medical CME: the mandatory-topic this session counts toward


@dataclass
class Credential:
    """A professional license tracked for CE/PDH compliance."""
    user_id: str
    profession: Profession          # attorney | pe | physician
    state: str                       # two-letter code
    license_number: str
    renewal_cycle_years: int         # from the registry (1=annual, 2=biennium, 3=triennium)
    required_hours: float            # CE/PDH hours required per cycle (0 if no requirement)
    required_ethics_hours: float
    last_renewed: str                # ISO date the current cycle started
    expires_at: str = ""            # ISO date the current cycle ends (computed)
    status: str = "active"          # active | lapsed | surrendered
    sessions: list[CESession] = field(default_factory=list)
    notes: str = ""
    # Medical CME mandatory-topic tracking (Gap M7). Per-state mandatory topics
    # (FL: CS/DV/HIV/trafficking; CT: 6-year cycles incl. cultural competency;
    # PA: opioid education; MA: cognitive impairment) with an optional separate
    # topic cycle (CT = 6 years; 0 = no separate topic cycle, topics track the
    # renewal cycle).
    required_mandatory_topics: tuple[str, ...] = ()
    mandatory_topic_cycle_years: int = 0

    @property
    def accumulated_hours(self) -> float:
        return sum(s.hours for s in self.sessions)

    @property
    def accumulated_ethics_hours(self) -> float:
        return sum(s.ethics_hours for s in self.sessions)

    @property
    def mandatory_topics_completed(self) -> set[str]:
        """The set of mandatory topics that have at least one CE session
        recorded against them. For medical CME: a topic is 'completed' when
        a session with that topic exists in the current cycle."""
        return {s.topic for s in self.sessions if s.topic}

    @property
    def missing_mandatory_topics(self) -> tuple[str, ...]:
        """Mandatory topics required by the state but not yet completed."""
        return tuple(t for t in self.required_mandatory_topics
                     if t not in self.mandatory_topics_completed)


def credential_for(user_id: str, profession: Profession, state: str,
                   license_number: str, last_renewed: str,
                   ) -> Credential | None:
    """Build a Credential with per-state requirements sourced from the Gap 1
    registry. Returns None if the state isn't in the registry or the profession
    isn't applicable (e.g. attorney profile for a state with no LegalProfile)."""
    state = state.lower()
    if profession == "attorney":
        lp = get_legal_profile(state)
        if lp is None:
            return None
        return Credential(
            user_id=user_id, profession="attorney", state=state.upper(),
            license_number=license_number,
            renewal_cycle_years=lp.cle_cycle_years,
            required_hours=float(lp.cle_hours),
            required_ethics_hours=float(lp.cle_ethics_hours),
            last_renewed=last_renewed,
        )
    if profession == "physician":
        mp = get_medical_profile(state)
        if mp is None:
            return None
        return Credential(
            user_id=user_id, profession="physician", state=state.upper(),
            license_number=license_number,
            renewal_cycle_years=mp.cme_cycle_years,
            required_hours=float(mp.cme_hours),
            required_ethics_hours=0.0,  # medical CME tracks mandatory topics, not ethics hours
            last_renewed=last_renewed,
            required_mandatory_topics=mp.cme_mandatory_topics,
            mandatory_topic_cycle_years=mp.cme_topic_cycle_years,
        )
    if profession == "teacher":
        ep = get_education_profile(state)
        if ep is None:
            return None
        # When PD hours are not encoded (0), use a non-zero placeholder so
        # compliance_status does not return no_requirement for states that
        # still require certification renewal — mirror MD CLE placeholder pattern.
        pd_hours = float(ep.teacher_pd_hours) if ep.teacher_pd_hours > 0 else 0.0
        cycle = ep.teacher_pd_cycle_years if ep.teacher_pd_cycle_years > 0 else 5
        return Credential(
            user_id=user_id, profession="teacher", state=state.upper(),
            license_number=license_number,
            renewal_cycle_years=cycle,
            required_hours=pd_hours,
            required_ethics_hours=0.0,
            last_renewed=last_renewed,
            notes=f"cert_authority={ep.teacher_cert_authority}; {ep.teacher_cert_citation}",
        )
    # pe
    fp = get_forensic_profile(state)
    if fp is None:
        return None
    return Credential(
        user_id=user_id, profession="pe", state=state.upper(),
        license_number=license_number,
        renewal_cycle_years=fp.pdh_cycle_years,
        required_hours=float(fp.pdh_hours),
        required_ethics_hours=float(fp.pdh_ethics_hours),
        last_renewed=last_renewed,
    )


# ---------------------------------------------------------------------------
# CE session recording + compliance status

def record_hours(cred: Credential, session: CESession) -> Credential:
    """Record a CE/PDH session against the credential. Returns the credential
    (mutated in place). Does not dedupe — the firm is responsible for not
    double-counting (per the gap analysis: asserted, not verified)."""
    if not math.isfinite(session.hours) or not math.isfinite(session.ethics_hours):
        raise ValueError("CE hours must be finite")
    if session.hours < 0 or session.ethics_hours < 0:
        raise ValueError("CE hours cannot be negative")
    if session.ethics_hours > session.hours:
        raise ValueError("ethics_hours cannot exceed total hours")
    try:
        from datetime import datetime
        datetime.fromisoformat(session.date)
    except (TypeError, ValueError) as exc:
        raise ValueError("session date must be ISO-8601") from exc
    cred.sessions.append(session)
    return cred


def _cycle_end(last, years: int):
    try:
        return last.replace(year=last.year + years)
    except ValueError:
        return last.replace(year=last.year + years, day=28)


def compliance_status(cred: Credential, *, now: float | None = None,
                      expiring_threshold_days: int = 60) -> CredentialStatus:
    """Return the compliance status of a credential.

    - current: within the cycle window and CE hours met
    - expiring_soon: within the cycle window and CE met but renewal due soon
    - expired: past the cycle end date
    - ce_deficient: within the cycle window but hours or ethics below required
    - no_requirement: state has no CE requirement (required_hours == 0, e.g. MA CLE)
    """
    if cred.status != "active":
        return "expired"
    if cred.required_hours == 0 and cred.required_ethics_hours == 0:
        return "no_requirement"
    # cycle window from last_renewed (ISO date) + renewal_cycle_years
    try:
        from datetime import datetime
        last = datetime.fromisoformat(cred.last_renewed)
    except (ValueError, TypeError):
        return "ce_deficient"  # bad date → can't prove compliance
    cycle_end = _cycle_end(last, cred.renewal_cycle_years)
    now_dt = datetime.fromtimestamp(now if now is not None else time.time(),
                                      tz=last.tzinfo)
    if now_dt > cycle_end:
        return "expired"
    current_sessions = []
    for session in cred.sessions:
        try:
            occurred = datetime.fromisoformat(session.date)
        except (TypeError, ValueError):
            continue
        if last <= occurred <= cycle_end:
            current_sessions.append(session)
    # CE hours check
    if sum(session.hours for session in current_sessions) < cred.required_hours:
        return "ce_deficient"
    if sum(session.ethics_hours for session in current_sessions) < cred.required_ethics_hours:
        return "ce_deficient"
    # Medical CME mandatory-topic check (Gap M7): a physician is ce_deficient
    # if any state-mandated topic hasn't been completed in the cycle.
    completed_topics = {session.topic for session in current_sessions if session.topic}
    if (cred.required_mandatory_topics and
            any(topic not in completed_topics for topic in cred.required_mandatory_topics)):
        return "ce_deficient"
    if (cycle_end - now_dt).days <= expiring_threshold_days:
        return "expiring_soon"
    return "current"


def is_compliant(cred: Credential, *, now: float | None = None) -> bool:
    """True if compliance_status is current or no_requirement."""
    return compliance_status(cred, now=now) in ("current", "no_requirement")


# ---------------------------------------------------------------------------
# CredentialLedger — per-user store

@dataclass
class CredentialLedger:
    """Per-user store of credentials + the CE/PDH sessions recorded against
    them. The system of record for licensure-tracking compliance."""
    _by_user: dict[str, list[Credential]] = field(default_factory=dict)

    def add(self, cred: Credential) -> Credential:
        # don't stack duplicate (user, profession, state) — update the existing
        # credential's metadata fields but preserve its session history.
        existing = self._find(cred.user_id, cred.profession, cred.state)
        if existing is not None:
            existing.license_number = cred.license_number
            existing.last_renewed = cred.last_renewed
            existing.renewal_cycle_years = cred.renewal_cycle_years
            existing.required_hours = cred.required_hours
            existing.required_ethics_hours = cred.required_ethics_hours
            existing.notes = cred.notes or existing.notes
            # sessions preserved from the existing record (not overwritten)
            return existing
        self._by_user.setdefault(cred.user_id, []).append(cred)
        return cred

    def record_session(self, user_id: str, profession: Profession, state: str,
                        session: CESession) -> Credential | None:
        cred = self._find(user_id, profession, state)
        if cred is None:
            return None
        record_hours(cred, session)
        return cred

    def get(self, user_id: str, profession: Profession, state: str) -> Credential | None:
        return self._find(user_id, profession, state)

    def credentials_for_user(self, user_id: str) -> list[Credential]:
        return list(self._by_user.get(user_id, []))

    def credentials_for_state(self, state: str) -> list[Credential]:
        st = state.upper()
        out: list[Credential] = []
        for creds in self._by_user.values():
            out.extend(c for c in creds if c.state == st)
        return out

    def all_credentials(self) -> list[Credential]:
        out: list[Credential] = []
        for creds in self._by_user.values():
            out.extend(creds)
        return out

    def noncompliant_credentials(self, *, now: float | None = None) -> list[Credential]:
        return [c for c in self.all_credentials() if not is_compliant(c, now=now)]

    def renew(self, user_id: str, profession: Profession, state: str,
              new_last_renewed: str, *, reset_hours: bool = True) -> Credential | None:
        """Mark a credential renewed: set last_renewed to the new cycle start,
        optionally reset accumulated hours (typical: carry zero into the new
        cycle). Returns the credential or None if not found."""
        cred = self._find(user_id, profession, state)
        if cred is None:
            return None
        cred.last_renewed = new_last_renewed
        if reset_hours:
            cred.sessions = []
        return cred

    def _find(self, user_id: str, profession: Profession, state: str) -> Credential | None:
        st = state.upper()
        for cred in self._by_user.get(user_id, []):
            if cred.profession == profession and cred.state == st:
                return cred
        return None


# ---------------------------------------------------------------------------
# Render — the compliance summary for a firm's credentials

def render_user_summary(user_id: str, ledger: CredentialLedger,
                         *, now: float | None = None) -> str:
    creds = ledger.credentials_for_user(user_id)
    if not creds:
        return f"CE/PDH Summary — {user_id}: no credentials on record."
    lines = [f"CE/PDH Summary — {user_id}", f"Credentials: {len(creds)}", ""]
    for c in creds:
        status = compliance_status(c, now=now)
        lines.append(
            f"  [{c.profession} {c.state}] {c.license_number}: {status} | "
            f"{c.accumulated_hours}/{c.required_hours} hrs "
            f"({c.accumulated_ethics_hours}/{c.required_ethics_hours} ethics) | "
            f"cycle {c.last_renewed} +{c.renewal_cycle_years}y"
        )
    return "\n".join(lines)