from __future__ import annotations
"""
Reddit adapter for the Music Culture Observation Engine.

Unauthenticated access via the public ``<url>.json`` endpoint — no PRAW, no
registered app, no client_id/client_secret. Weekly ``t=week`` top listings,
``top_n_per_sub`` selection (NOT a global min_score — cross-sub dynamic range is
too large for a flat threshold), persistent session with retry/backoff, and an
HTML-not-JSON guard for Reddit's cold-request bot challenge.

Fail-open contract: any per-sub failure logs and yields zero items for that sub;
the run continues. The adapter never raises to the pipeline.

Config keys (under sources.reddit):
  subreddits       (list) — subreddit names (exact, case-sensitive on Reddit)
  top_n_per_sub    (int)  — keep the top N per sub after sort (default 5)
  fetch_limit      (int)  — listing rows to request per sub (default 25)
  time_filter      (str)  — Reddit 'top' window: hour/day/week/month/year/all (default 'week')
  min_score_floor  (int)  — discard posts below this score BEFORE top-N (default 0; a low
                            noise floor, not a popularity gate)
  deep_dive        (bool) — fetch comment trees for funnel survivors (default True; the
                            funnel does the per-survivor calls, not this bulk fetch)

The funnel (engine/relevance.py) consumes the per-item ``wire`` dict this adapter
attaches (score, num_comments, upvote_ratio, is_video, is_self, domain, flair).
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

USER_AGENT = "script:observation-engine:v1.0"
_BASE = "https://www.reddit.com"
_RETRY_BACKOFF_S = (1.0, 3.0, 6.0)   # three retries on transient/HTML-challenge


def _new_session():
    """A persistent requests.Session with the descriptive UA. Warm cookies pass
    Reddit's edge bot challenge that blocks the first cold request."""
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _looks_like_html(text: str) -> bool:
    """Reddit's bot-challenge / error pages come back as HTML, not JSON. Detect
    so we retry-with-backoff rather than crashing the JSON parse."""
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html") or "<head" in head


def _get_json(session, url, *, params=None, sleep=time.sleep):
    """GET a Reddit .json endpoint with retry/backoff + HTML guard.

    Returns the parsed JSON object, or None on exhausted retries / hard failure.
    Never raises — the adapter's fail-open contract depends on this.
    """
    import json as _json
    for attempt, backoff in enumerate((0.0,) + _RETRY_BACKOFF_S):
        if backoff:
            sleep(backoff)
        try:
            resp = session.get(url, params=params, timeout=30)
        except Exception as exc:  # network error — retry
            logger.warning("Reddit GET error (%s) attempt %d: %s", url, attempt, exc)
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            logger.warning("Reddit %s returned %d — backing off (attempt %d)",
                           url, resp.status_code, attempt)
            continue
        if resp.status_code != 200:
            logger.error("Reddit %s returned %d — giving up", url, resp.status_code)
            return None
        text = resp.text or ""
        if _looks_like_html(text):
            logger.warning("Reddit %s returned HTML (bot challenge) — retry (attempt %d)",
                           url, attempt)
            continue
        try:
            return _json.loads(text)
        except ValueError as exc:
            logger.warning("Reddit %s JSON parse failed: %s — retry", url, exc)
            continue
    logger.error("Reddit %s failed after retries — failing open (0 items).", url)
    return None


def _parse_listing(payload, subreddit_name):
    """Map a Reddit listing JSON payload to adapter result dicts (+ wire metrics)."""
    out = []
    try:
        children = payload["data"]["children"]
    except (KeyError, TypeError):
        return out
    for child in children:
        d = child.get("data", {}) if isinstance(child, dict) else {}
        if not d or d.get("stickied"):
            continue
        permalink = f"{_BASE}{d.get('permalink', '')}"
        selftext = (d.get("selftext") or "").strip()
        score = int(d.get("score", 0) or 0)
        if selftext:
            body = selftext[:500]
        else:
            body = (f"Posted in r/{subreddit_name} with {score} upvotes. "
                    f"Link: {d.get('url', '')}")[:500]
        try:
            published_date = datetime.fromtimestamp(
                float(d.get("created_utc", 0)), tz=timezone.utc
            ).strftime("%Y-%m-%d")
        except Exception:
            published_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        flair = (d.get("link_flair_text") or "")
        raw_tags = [subreddit_name]
        if flair:
            raw_tags.append(flair.lower().replace(" ", "-"))

        out.append({
            "source": f"Reddit/r/{subreddit_name}",
            "source_url": permalink,
            "title": d.get("title", ""),
            "body": body,
            "published_date": published_date,
            "raw_tags": raw_tags,
            # Wire metrics consumed by the Stage-1 pre-rank (engine/relevance.py).
            "wire": {
                "subreddit": subreddit_name,
                "score": score,
                "num_comments": int(d.get("num_comments", 0) or 0),
                "upvote_ratio": float(d.get("upvote_ratio", 0.0) or 0.0),
                "is_video": bool(d.get("is_video", False)),
                "is_self": bool(d.get("is_self", False)),
                "domain": d.get("domain", ""),
                "flair": flair,
                "permalink": d.get("permalink", ""),
            },
        })
    return out


def fetch(config: dict, *, session=None, sleep=time.sleep) -> list[dict]:
    """Fetch top-N-per-sub weekly posts across config['subreddits'] (Stage 0).

    ``session``/``sleep`` are injectable for hermetic testing. In production both
    default to a live session and real sleep.
    """
    subreddits = config.get("subreddits", []) or []
    top_n = int(config.get("top_n_per_sub", 5))
    fetch_limit = int(config.get("fetch_limit", 25))
    time_filter = str(config.get("time_filter", "week"))
    min_score_floor = int(config.get("min_score_floor", 0))

    if session is None:
        session = _new_session()

    results: list[dict] = []
    seen_urls: set[str] = set()

    for sub in subreddits:
        url = f"{_BASE}/r/{sub}/top.json"
        payload = _get_json(session, url,
                            params={"t": time_filter, "limit": fetch_limit},
                            sleep=sleep)
        if payload is None:
            continue  # fail-open: this sub contributes nothing, run continues
        items = _parse_listing(payload, sub)
        # Noise floor (NOT a popularity gate), then top-N per sub by score.
        items = [it for it in items if it["wire"]["score"] >= min_score_floor]
        items.sort(key=lambda it: it["wire"]["score"], reverse=True)
        kept = 0
        for it in items:
            if it["source_url"] in seen_urls:
                continue
            seen_urls.add(it["source_url"])
            results.append(it)
            kept += 1
            if kept >= top_n:
                break
        logger.info("Reddit r/%s: kept %d of %d (t=%s, floor=%d)",
                    sub, kept, len(items), time_filter, min_score_floor)

    return results


def fetch_comments(permalink_path: str, *, session=None, sleep=time.sleep,
                   top_k: int = 12) -> list[str]:
    """Stage-3 deep-dive: fetch the comment tree for one post's permalink.

    Returns up to ``top_k`` top-level comment bodies (the cultural signal —
    reactions, debate, slang — titles alone miss). Fail-open: [] on any failure.
    """
    if session is None:
        session = _new_session()
    url = f"{_BASE}{permalink_path.rstrip('/')}.json"
    payload = _get_json(session, url, sleep=sleep)
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    bodies = []
    try:
        children = payload[1]["data"]["children"]
    except (KeyError, TypeError, IndexError):
        return []
    for child in children:
        d = child.get("data", {}) if isinstance(child, dict) else {}
        body = (d.get("body") or "").strip()
        if body and body not in ("[deleted]", "[removed]"):
            bodies.append(body[:600])
        if len(bodies) >= top_k:
            break
    return bodies
