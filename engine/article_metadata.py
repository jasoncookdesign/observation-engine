"""Provider-neutral article-note metadata for INI-138 Phase 3.

The observation engine already has the source facts and a bounded model
summary. This module turns those facts into the metadata contract consumed by
the Reel Producer without inventing new source content.
"""
from __future__ import annotations

import re
from datetime import date


RELEVANCE_TAXONOMY = (
    "dj_culture", "music_production", "music_business", "artist_identity",
    "club_culture", "rave_history", "technology", "platform_economics",
    "promotion", "event_operations", "label_operations",
)

_TAXONOMY_ALIASES = {
    "dj": "dj_culture", "djing": "dj_culture", "mixing": "dj_culture",
    "dancefloor": "club_culture", "club": "club_culture", "rave": "rave_history",
    "production": "music_production", "producer": "music_production",
    "technology": "technology", "tech": "technology", "software": "technology",
    "bandcamp": "platform_economics", "streaming": "platform_economics",
    "platform": "platform_economics", "label": "label_operations",
    "release": "promotion", "marketing": "promotion", "booking": "event_operations",
    "artist": "artist_identity", "identity": "artist_identity",
}


def _clean_list(value) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]


def _time_sensitivity(published_date: str) -> str:
    try:
        age = (date.today() - date.fromisoformat(str(published_date)[:10])).days
    except (TypeError, ValueError):
        return "unknown"
    if age <= 30:
        return "high"
    if age <= 365:
        return "medium"
    return "low"


def build(raw: dict, parsed: dict | None = None) -> dict:
    """Build the Phase-3 metadata block from source facts and model output."""
    parsed = parsed or {}
    title = str(raw.get("title") or parsed.get("title") or "").strip()
    publication = str(raw.get("source") or "").strip()
    published_date = str(raw.get("published_date") or raw.get("date") or "").strip()
    summary = str(parsed.get("observation") or raw.get("title") or "").strip()
    context = str(parsed.get("expanded_context") or "").strip()
    claims = _clean_list(parsed.get("claims")) or _sentences(context)
    topics = _clean_list(parsed.get("topics")) or _clean_list(parsed.get("tags") or raw.get("raw_tags"))
    entities = _clean_list(parsed.get("entities"))
    relevance = [_TAXONOMY_ALIASES.get(t.lower().replace("-", " "), t)
                 for t in topics]
    topic_blob = " ".join(topics).lower()
    relevance += [_TAXONOMY_ALIASES[t] for t in _TAXONOMY_ALIASES if t in topic_blob]
    relevance = list(dict.fromkeys(r for r in relevance if r in RELEVANCE_TAXONOMY))
    if not relevance:
        relevance = ["music_production"]
    return {
        "note_id": str(raw.get("note_id") or "").strip(),
        "title": title,
        "publication": publication,
        "publication_date": published_date,
        "source_url": str(raw.get("source_url") or "").strip(),
        "author": str(raw.get("author") or "").strip(),
        "topics": topics,
        "entities": entities,
        "summary": summary,
        "claims": claims,
        "relevance": relevance,
        "time_sensitivity": str(parsed.get("time_sensitivity") or _time_sensitivity(published_date)),
    }
