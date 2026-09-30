# SMF Praxis Legal

Law Firm compliance pack for the [Praxis](https://github.com/smfworks/smf-praxis) autonomous agent platform.

This pack is informational tooling and not legal advice. Users should verify requirements with qualified counsel.

## Status

Extracted from `smf-praxis` base on 2026-07-19 during the vertical-extraction cutover (option 2b-iii). This repo contains the pack-specific code that was removed from the public base; it depends on the open-core base (`smf-praxis`) as a runtime dependency.

## What's inside

- **6 compliance modules** — `advertising_filing`, `conflicts`, `credentials`, `discovery_templates`, `legal_hold`, `security_attestation`
- **Law Firm pack** — `packs/law_firm/` (manifest + knowledge base), persona + authority policy for `verticals/legal/`
- **Dashboard assets** — `web/law_firm.{css,js}`
- **5 eval cases** — UPL guardrail, NY ad-filing gate, MA WISP attestation, conflict check, CLE status
- **13-state coverage** — FL, GA, SC, TN, VA, WV, MD, PA, OH, NJ, NY, CT, MA

## Installation

```bash
pip install smf-praxis          # open-core base (MIT)
pip install praxis-legal        # this pack (MIT)
```

Importing `hybridagent_praxis_legal` auto-registers the Law Firm pack with the base's plugin registry, lighting up its pack, eval cases, and dashboard routes.

## Compliance posture

**Enforced.** READ + DRAFT autonomous; SEND + DESTRUCTIVE held for human approval. The Law Firm persona carries UPL + IOLTA + trust-accounting guardrails across all 13 states.

## License

This pack is MIT-licensed. See [LICENSE](LICENSE).
