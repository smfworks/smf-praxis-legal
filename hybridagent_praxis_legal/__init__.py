"""SMF Praxis Legal vertical — registration module.

This package is the private paid Law Firm vertical build for Praxis. It
depends on the open-core ``smf-praxis`` base and registers the legal
vertical's spec, dashboard routes, and eval cases with the base's
:mod:`hybridagent.verticals.registry` on import.

Installation::

    pip install smf-praxis          # open-core base (public, MIT)
    pip install smf-praxis-legal    # this vertical (private, commercial)

Activating the vertical lights up:

  * the ``law_firm`` vertical pack (persona + knowledge + compliance modules),
  * the ``vertical.law_firm.*`` eval cases (UPL guardrail, NY ad-filing,
    MA WISP attestation, conflict check, CLE status), and
  * the law-firm dashboard routes in the Command Deck.

The vertical-specific modules (``advertising_filing``, ``conflicts``,
``credentials``, ``discovery_templates``, ``legal_hold``,
``security_attestation``) are imported lazily by the eval cases and
daemon routes that need them — they are not imported at package load
time, keeping the vertical install lightweight and the base's
dependency-free core invariant intact.

Compliance mode: ``enforced``. READ + DRAFT autonomous; SEND + DESTRUCTIVE
held for human approval. The Law Firm persona carries UPL + IOLTA +
trust-accounting guardrails across all 13 states.
"""

from __future__ import annotations

from .registration import register

__version__ = "0.1.1"

__all__ = ["register", "__version__"]

# Auto-register on import so ``import hybridagent_praxis_legal`` lights up
# the vertical for the whole process lifetime.
register()