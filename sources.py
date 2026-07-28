# src/news_sources.py
"""Curated 'AI News' source set + feed-resolution helpers.

Bundles the user's target outlets mapped to their best ingestion strategy
(verified 2026-07-24), and provides `best_feed()` — a known-host map + common
feed-suffix candidates used by NewsResearcher._resolve_feed before it falls
back to parsing <link rel="alternate"> from the page HTML.

Strategy codes:
  A = native/discoverable RSS/Atom feed (most reliable)
  B = static HTML index page → article-link discovery (best-effort)
  C = no feed + JS-rendered SPA (flagged needs_js; deferred to a later phase)
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

# Each entry: name, url (as the user provides it), feed (resolved, or None),
# strategy, flags (paywall | needs_js | ua_sensitive).
AI_NEWS_SOURCES: List[Dict] = [
    {"name": "OpenAI News", "url": "https://openai.com/news", "feed": "https://openai.com/news/rss.xml", "strategy": "A", "flags": []},
    {"name": "OpenAI Blog", "url": "https://openai.com/blog", "feed": "https://openai.com/news/rss.xml", "strategy": "A", "flags": []},
    {"name": "Google DeepMind", "url": "https://deepmind.google/discover/blog/", "feed": "https://deepmind.google/blog/rss.xml", "strategy": "A", "flags": []},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog", "feed": "https://huggingface.co/blog/feed.xml", "strategy": "A", "flags": []},
    {"name": "arXiv cs.CL", "url": "https://arxiv.org/list/cs.CL/recent", "feed": "https://rss.arxiv.org/rss/cs.CL", "strategy": "A", "flags": []},
    {"name": "arXiv cs.LG", "url": "https://arxiv.org/list/cs.LG/recent", "feed": "https://rss.arxiv.org/rss/cs.LG", "strategy": "A", "flags": []},
    {"name": "vLLM Releases", "url": "https://github.com/vllm-project/vllm/releases", "feed": "https://github.com/vllm-project/vllm/releases.atom", "strategy": "A", "flags": []},
    {"name": "LangChain Releases", "url": "https://github.com/langchain-ai/langchain/releases", "feed": "https://github.com/langchain-ai/langchain/releases.atom", "strategy": "A", "flags": []},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence", "feed": "https://techcrunch.com/category/artificial-intelligence/feed/", "strategy": "A", "flags": []},
    {"name": "The Verge AI", "url": "https://www.theverge.com/ai-artificial-intelligence", "feed": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "strategy": "A", "flags": ["ua_sensitive"]},
    {"name": "Latent Space", "url": "https://www.latent.space/", "feed": "https://www.latent.space/feed", "strategy": "A", "flags": []},
    {"name": "SemiAnalysis", "url": "https://www.semianalysis.com/", "feed": "https://www.semianalysis.com/feed", "strategy": "A", "flags": []},
    {"name": "r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/", "feed": "https://www.reddit.com/r/LocalLLaMA/.rss", "strategy": "A", "flags": ["ua_sensitive"]},
    {"name": "Stratechery", "url": "https://stratechery.com/", "feed": "https://stratechery.com/feed/", "strategy": "A", "flags": ["paywall"]},
    {"name": "NIST AI", "url": "https://www.nist.gov/artificial-intelligence", "feed": None, "strategy": "B", "flags": []},
    {"name": "EU AI Office", "url": "https://digital-strategy.ec.europa.eu/en/policies/ai-office", "feed": None, "strategy": "B", "flags": []},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/news", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "Meta AI", "url": "https://ai.meta.com/blog/", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "Mistral", "url": "https://mistral.ai/news/", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "xAI", "url": "https://x.ai/blog", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "Anthropic Docs Changelog", "url": "https://docs.anthropic.com/en/release-notes/api", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "Google AI Studio Release Notes", "url": "https://ai.google.dev/gemini-api/docs/changelog", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "OpenAI Changelog", "url": "https://platform.openai.com/docs/changelog", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "GitHub Trending (AI)", "url": "https://github.com/trending", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    {"name": "Hugging Face Trending", "url": "https://huggingface.co/models", "feed": None, "strategy": "C", "flags": ["needs_js"]},
    # The Information is intentionally omitted from the default preset (hard paywall).
]

# Explicit host→feed map for hosts where a bare page URL should map to a feed.
_HOST_FEED_MAP = {
    ("openai.com", None): "https://openai.com/news/rss.xml",
    ("deepmind.google", None): "https://deepmind.google/blog/rss.xml",
}

# Common feed-path candidates probed (in order) when no explicit map hit.
FEED_SUFFIXES = ["feed", "rss.xml", "feed.xml", "atom.xml", "rss", "index.xml"]


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().lstrip("www.")
    except Exception:
        return ""


def known_strategy(url: str) -> Optional[str]:
    """Return the curated preset's strategy ('A'|'B'|'C') for a URL, else None.

    Lets the engine skip feed-suffix probing for sources we already know have no
    feed (strategy B/C) — that probing is the slow part of the resolve phase.
    """
    norm = (url or "").rstrip("/")
    for s in AI_NEWS_SOURCES:
        if s["url"].rstrip("/") == norm:
            return s.get("strategy")
    return None


def preset_feed(url: str) -> Optional[str]:
    """Exact/normalized lookup against the curated preset (highest confidence)."""
    norm = url.rstrip("/")
    for s in AI_NEWS_SOURCES:
        if s["url"].rstrip("/") == norm and s.get("feed"):
            return s["feed"]
    return None


def best_feed(url: str) -> Optional[str]:
    """Return a known feed URL for `url` via preset + host map, else None.

    Also handles the GitHub releases → `.atom` and Reddit → `.rss` conventions
    and arXiv listing → rss.arxiv.org.
    """
    hit = preset_feed(url)
    if hit:
        return hit

    host = _host(url)
    path = urlparse(url).path or ""

    # GitHub releases → append .atom
    m = re.match(r"^https?://github\.com/([^/]+)/([^/]+)/releases/?$", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/releases.atom"

    # Reddit subreddit → .rss
    m = re.match(r"^https?://(www\.)?reddit\.com/r/([^/]+)/?$", url)
    if m:
        return f"https://www.reddit.com/r/{m.group(2)}/.rss"

    # arXiv listing → rss.arxiv.org
    m = re.match(r"^https?://arxiv\.org/list/([^/]+)/", url)
    if m:
        return f"https://rss.arxiv.org/rss/{m.group(1)}"

    for (h, p), feed in _HOST_FEED_MAP.items():
        if host == h and (p is None or path.startswith(p)):
            return feed
    return None


def preset_source_set() -> Dict:
    """The bundled, read-only 'AI News' source set for the UI/source-set API."""
    return {
        "id": "builtin-ai-news",
        "name": "AI News",
        "builtin": True,
        "sources": [s["url"] for s in AI_NEWS_SOURCES],
        "keywords": [],
        "time_window_hours": 24,
        "per_feed_limit": 10,
        "entries": AI_NEWS_SOURCES,
    }
