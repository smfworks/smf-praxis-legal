"""Registration — wire the legal vertical into the Praxis base registry.

Called once on import of :mod:`hybridagent_praxis_legal`. Registers:

  * the ``law_firm`` :class:`VerticalSpec` (persona keyword, compliance mode,
    autonomous/held risk classes),
  * a factory returning the 5 manual law-firm eval cases, and
  * the authenticated law-firm dashboard route registrar.

The manual eval cases import the vertical-specific modules lazily (inside
the factory's runnables), so simply installing this package does not
import the compliance modules — they load only when an eval case or
dashboard route actually executes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hybridagent.broker import RiskClass
from hybridagent.evals import EvalCase
from hybridagent.verticals.registry import (
    VerticalSpec,
    register_vertical_eval_cases,
    register_vertical_pack_root,
    register_vertical_routes,
    register_vertical_spec,
    register_vertical_web_root,
)

_LEGAL_PERSONA_SPEC = VerticalSpec(
    name="legal",
    persona_keyword="legal",
    compliance_mode="enforced",
    autonomous={RiskClass.READ},
    held={RiskClass.SEND, RiskClass.DESTRUCTIVE},
    version="0.2.1",
)

_LEGAL_SPEC = VerticalSpec(
    name="law_firm",
    persona_keyword="law firm",
    compliance_mode="enforced",
    autonomous={RiskClass.READ, RiskClass.DRAFT},
    held={RiskClass.SEND, RiskClass.DESTRUCTIVE},
    version="0.2.1",
)


def _upl_guardrail_case():
    def run() -> tuple[bool, str]:
        from hybridagent import vertical_templates as vt
        from hybridagent.pack import VerticalPack
        t = vt.get_template("law_firm") or {}
        pk = VerticalPack.from_manifest({**t, "name": "law_firm"})
        sp = pk.system_prompt.lower()
        checks = {
            "UPL": "do not provide legal advice" in sp,
            "IOLTA": "iolta" in sp,
            "trust_acct": "trust accounting" in sp,
            "no_mdp_implicit": "never send, file, or sign" in sp,
        }
        ok = all(checks.values())
        return ok, ",".join(k for k, v in checks.items() if v) or "missing"
    return run


def _ny_ad_filing_case():
    def run() -> tuple[bool, str]:
        from .modules.advertising_filing import AdvertisingFiling, validate_before_send
        f = AdvertisingFiling(artifact_id="ad-1", jurisdiction="NY", status="draft")
        findings = validate_before_send(f)
        blocked = any(x.severity == "critical" and x.field == "label_present"
                      for x in findings)
        return blocked, "label-missing blocked" if blocked else "NOT blocked"
    return run


def _ma_wisp_case():
    def run() -> tuple[bool, str]:
        from .modules.security_attestation import SecurityControls, attest
        att = attest("MA", SecurityControls())
        return (not att.passed and
                any(x.severity == "critical" and x.control == "wisp_on_file"
                    for x in att.findings),
                att.summary()[:60])
    return run


def _conflict_case():
    def run() -> tuple[bool, str]:
        from hybridagent.workspaces import Workspace

        from .modules.conflicts import ConflictChecker, ConflictHit, PartyName

        class _FakeDir:
            def __init__(self, matters):
                self._m = matters
            def list_for(self, org):
                return [m for m in self._m if m.organization_id == org]

        ws = Workspace(
            workspace_id="ws-1", organization_id="org-1", human_identifier="ws-1",
            kind="matter", title="Smith v Jones", client_or_subject="Jane Smith",
            owner_user_id="a", team_id="t", status="active", confidentiality="internal",
            jurisdiction="NY", location="", opened_date="2026-01-01", target_date="",
            field_schema={}, custom_fields={}, external_links=(),
            legal_hold=False, hold_reason="", created_ts=0.0, updated_ts=0.0)
        checker = ConflictChecker(_FakeDir([ws]))
        report = checker.check(
            prospective_parties=[PartyName("Jane Smith", "opposing")],
            organization_id="org-1", authorized_by="atty-1")
        no_leak = (not hasattr(ConflictHit, "content") and
                   not hasattr(ConflictHit, "memory"))
        return (not report.clean and no_leak and len(report.hits) == 1,
                f"hits={len(report.hits)} no_leak={no_leak}")
    return run


def _cle_case():
    def run() -> tuple[bool, str]:
        from .modules.credentials import (
            CESession,
            compliance_status,
            credential_for,
            record_hours,
        )
        ny = credential_for("u", "attorney", "NY", "1", "2026-01-01")
        assert ny is not None, "NY attorney profile must exist"
        record_hours(ny, CESession(date="2026-02-01", hours=24, ethics_hours=1))
        ny_def = compliance_status(ny) == "ce_deficient"
        ma = credential_for("u", "attorney", "MA", "1", "2026-01-01")
        assert ma is not None, "MA attorney profile must exist"
        ma_none = compliance_status(ma) == "no_requirement"
        return (ny_def and ma_none,
                f"ny={compliance_status(ny)} ma={compliance_status(ma)}")
    return run


def _manual_cases() -> list[EvalCase]:
    """Factory: return the 5 manual law-firm eval cases."""

    return [
        EvalCase("vertical.law_firm.upl_guardrail", "vertical",
                 "Law Firm persona carries the UPL + IOLTA guardrails (all 13 states).",
                 _upl_guardrail_case()),
        EvalCase("vertical.law_firm.ny_ad_filing_gate", "vertical",
                 "NY advertising missing the label is blocked (22 NYCRR 1200).",
                 _ny_ad_filing_case()),
        EvalCase("vertical.law_firm.ma_wisp_attestation", "vertical",
                 "MA matter without a WISP fails the 201 CMR 17.00 attestation.",
                 _ma_wisp_case()),
        EvalCase("vertical.law_firm.conflict_check", "vertical",
                 "Conflict check surfaces hits without leaking matter content.",
                 _conflict_case()),
        EvalCase("vertical.law_firm.cle_status", "vertical",
                 "NY attorney with insufficient ethics hours is CE-deficient; MA is no-requirement.",
                 _cle_case()),
    ]


def _handle_routes(handler: Any) -> bool:
    path = str(handler.path).split("?", 1)[0]
    if handler.command != "GET" or path != "/api/law_firm":
        return False
    if not handler._require_auth():
        return True
    handler._json_response(handler.daemon.law_firm_compliance())
    return True


def register() -> None:
    """Register the legal vertical with the Praxis base registry.

    Idempotent: safe to call multiple times (the registry deduplicates specs
    by name and factories by identity).
    """

    register_vertical_spec(_LEGAL_PERSONA_SPEC)
    register_vertical_spec(_LEGAL_SPEC)
    register_vertical_eval_cases(_manual_cases)
    register_vertical_routes(_handle_routes)
    register_vertical_pack_root(Path(__file__).resolve().parent / "packs")
    register_vertical_web_root(Path(__file__).resolve().parent / "web")