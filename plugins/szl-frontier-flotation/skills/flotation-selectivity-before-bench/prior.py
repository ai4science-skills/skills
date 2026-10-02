"""Abstaining flotation-reagent selectivity prior.

S is a unitless logistic prior, not recovery. Missing descriptors or unset
weights ABSTAIN. A low |2S-1| margin ABSTAINS. This module has no package
import so the public skill folder stays portable.
"""

from __future__ import annotations

from typing import Any, Mapping

NEEDED = (
    "homo_lumo_gap_eV",
    "dipole_D",
    "surface_charge",
    "pH",
    "collector_mM",
)
DEFAULT_TAU = 0.15
NOT_RECOVERY = "flotation recovery"


def prior(
    features: Mapping[str, Any] | None,
    weights: Mapping[str, Any] | None,
    tau: float = DEFAULT_TAU,
) -> dict[str, Any]:
    """Return ABSTAIN or PRIOR_ONLY. recovery is never emitted."""

    source = features if isinstance(features, Mapping) else {}
    missing = [key for key in NEEDED if source.get(key) is None]
    if missing or not weights:
        return {
            "state": "ABSTAIN",
            "reason": "missing descriptor or unset weights",
            "missing": missing,
            "S": None,
            "S_class": "UNAVAILABLE",
            "not": NOT_RECOVERY,
            "tau": tau,
        }
    try:
        z = sum(float(weights[key]) * float(source[key]) for key in NEEDED)
        s = 1.0 / (1.0 + pow(2.718281828, -z))
    except (KeyError, TypeError, ValueError):
        return {
            "state": "ABSTAIN",
            "reason": "missing descriptor or unset weights",
            "missing": missing,
            "S": None,
            "S_class": "UNAVAILABLE",
            "not": NOT_RECOVERY,
            "tau": tau,
        }
    if abs(2 * s - 1) < tau:
        return {
            "state": "ABSTAIN",
            "reason": f"|2S-1|<{tau}",
            "missing": [],
            "S": round(s, 6),
            "S_class": "SIMULATED",
            "not": NOT_RECOVERY,
            "tau": tau,
        }
    return {
        "state": "PRIOR_ONLY",
        "reason": "unitless prior; not recovery",
        "missing": [],
        "S": round(s, 6),
        "S_class": "SIMULATED",
        "not": NOT_RECOVERY,
        "tau": tau,
    }
