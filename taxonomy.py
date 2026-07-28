# src/news_taxonomy.py
"""Taxonomy + scoring model for News Briefing mode.

Defines the five independent classification dimensions the briefing dashboard
filters on (Format is a UI render mode, not stored on the item), the per-item
score vector, and the server-side coercion/validation helpers that keep
LLM-produced tags on-enum and scores in range. `overall` is computed
deterministically here — never trusted from the model — so ranking and the
"Top Signal" pick are consistent and testable.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

# --- Format: a UI render mode, listed here for reference/validation only ---
FORMATS = [
    "Full Briefing", "5-Minute Read", "Developer View",
    "Non-Developer View", "Founder / GTM", "Content Creator",
]

# --- Window: recency filter → hours (None = all time) ---
WINDOWS: Dict[str, Optional[int]] = {
    "2h": 2, "24h": 24, "7d": 24 * 7, "30d": 24 * 30, "all": None,
}

# --- Category: single topical bucket ("All" is UI-only) ---
CATEGORIES = [
    "Models", "Developer Tools", "Open Source", "Infrastructure",
    "Agents", "Research", "Business", "Policy",
]
DEFAULT_CATEGORY = "Research"

# --- Signal: single editorial-importance class ("All" is UI-only) ---
SIGNALS = [
    "HIGH SIGNAL", "BUILDER USEFUL", "WATCH", "RESEARCH SIGNAL",
    "BUSINESS SIGNAL", "POLICY SIGNAL", "NOISE",
]
DEFAULT_SIGNAL = "WATCH"

# --- Audience: multi-valued ---
AUDIENCES = [
    "AI Engineers", "Software Engineers", "AI PMs", "Founders", "Operators",
    "DevRel", "Educators", "Creators", "Consultants", "GTM", "Enterprise",
    "Non-Developers", "Students",
]

# --- Secondary status tags ---
STATUS_TAGS = ["BUSINESS", "SECONDARY", "PARTIAL", "DEVELOPING"]

# --- Score vector keys (0..100). hype_risk is inverse-desirable. ---
SCORE_KEYS = ["practical", "technical", "market", "hype_risk", "urgency"]

# Weights for the deterministic `overall` composite. Tunable in one place.
_OVERALL_WEIGHTS = {
    "practical": 0.30, "technical": 0.25, "market": 0.20,
    "urgency": 0.15, "hype_risk": -0.20,
}
_OVERALL_BASE = 20.0


def clamp_score(value: Any) -> int:
    """Coerce an arbitrary LLM value into an int in [0, 100]."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, n))


def _nearest(value: Any, options: List[str], cutoff: float = 0.6) -> Optional[str]:
    """Map a free-text value to the nearest enum option, or None."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    for o in options:  # exact, case-insensitive
        if o.lower() == v.lower():
            return o
    match = difflib.get_close_matches(v, options, n=1, cutoff=cutoff)
    return match[0] if match else None


def coerce_category(value: Any) -> str:
    return _nearest(value, CATEGORIES) or DEFAULT_CATEGORY


def coerce_signal(value: Any) -> str:
    return _nearest(value, SIGNALS) or DEFAULT_SIGNAL


def coerce_audiences(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [p.strip() for p in value.replace(";", ",").split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value:
        m = _nearest(item, AUDIENCES)
        if m and m not in out:
            out.append(m)
    return out


def coerce_status_tags(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [p.strip() for p in value.replace(";", ",").split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value:
        m = _nearest(item, STATUS_TAGS, cutoff=0.7)
        if m and m not in out:
            out.append(m)
    return out


def coerce_scores(value: Any) -> Dict[str, int]:
    """Return a clean {key: 0..100} sub-vector (no `overall`)."""
    src = value if isinstance(value, dict) else {}
    return {k: clamp_score(src.get(k)) for k in SCORE_KEYS}


def compute_overall(scores: Dict[str, int]) -> int:
    """Deterministic weighted composite from the sub-scores."""
    total = _OVERALL_BASE
    for key, weight in _OVERALL_WEIGHTS.items():
        total += weight * clamp_score(scores.get(key))
    return max(0, min(100, int(round(total))))


def window_to_hours(window: Any) -> Optional[int]:
    """Map a window enum ('24h', '7d', ...) to hours; None if all/unknown."""
    if window is None:
        return None
    return WINDOWS.get(str(window).strip().lower())
