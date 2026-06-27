from __future__ import annotations
"""
Reddit adapter for the Music Culture Observation Engine.

⚠️  SOURCE IS DARK (INI-100, decision 2026-06-27). This adapter is dormant —
    `sources.reddit.enabled: false` in the instance config, so the pipeline never
    calls it. No viable Reddit access path exists:
      • unauthenticated `.json` → HTTP 403 (edge block, every UA/host/IP);
      • authenticated OAuth      → API-app creation gated by Reddit's Responsible
        Builder Policy (weeks-long manual pre-approval, commonly denied);
      • public RSS (below)       → works but Reddit rate-limits it to ~2 subs
        before sustained 429s, so it can't reliably cover the sub set.
    The code (and the engine/relevance.py funnel) is retained, tested, and ready
    to re-light if access ever opens. See configs/dyson-hope.yaml and INI-100.

ACCESS MODE (when re-enabled): public RSS feeds.
  Reddit blocks unauthenticated `.json` listing access at the edge (HTTP 403 with
  an HTML challenge page) regardless of User-Agent or host, and API-app creation
  is gated behind Reddit's Responsible Builder Policy (a new account cannot
  register a client_id/secret). The one public, no-credential path that still
  returns data is the per-subreddit Atom feed:

      https://www.reddit.com/r/<sub>/top/.rss?t=<window>

  This adapter fetches those feeds with a persistent session, a browser-like
  User-Agent (Reddit rejects bot-style UAs), retry/backoff on 429/5xx, and a
  polite inter-request delay (Reddit rate-limits unauthenticated RSS hard).

  TRADE-OFF vs `.json`: the Atom feed carries titles, permalinks, dates, author,
  and the post body, but NOT score / num_comments / upvote_ratio / flair-as-metric.
  So the relevance funnel's Stage-1 wire pre-rank is degraded (it falls back to
  taxonomy + content-type, and the feed's own top-sort as the tiebreaker), and
  Stage-3 comment deep-dive (which needs `.json`) is unavailable. Stage-2 (the
  lens-anchored LLM reaction-worthiness gate — the real precision step) and
  Stage-5 (feedback) are unaffected. The `wire` dict below keeps the full shape
  with metrics defaulted to 0 and `metrics_available: False`, so if an
  authenticated (OAuth) transport is ever added, the metrics populate and the
  funnel sharpens with no funnel-code change.

  ToS: public RSS is a reader-facing feed; this is materially lower-risk than
  `.json` scraping. The accept-and-document disposition in INI-100 still applies.

Fail-open contract: any per-sub failure logs and yields zero items for that sub;
the run continues. The adapter never raises to the pipeline.

Config keys (under sources.reddit):
  access           (str)  — "rss" (default) or "json" (legacy; Reddit-blocked)
  subreddits       (list) — subreddit names (exact, case-sensitive on Reddit)
  top_n_per_sub    (int)  — keep the top N per sub (feed is already top-sorted; default 5)
  time_filter      (str)  — top window: hour/day/week/month/year/all (default 'week')
  request_delay_s  (num)  — polite delay between sub requests (default 3.0; avoids 429)
"""

import logging
import re
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Reddit rejects bot/script User-Agents; a browser UA returns the RSS feed.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_BASE = "https://www.reddit.com"
_RETRY_BACKOFF_S = (2.0, 5.0, 10.0)   # retries on 429/5xx/HTML-challenge


def _new_session():
    """Persistent requests.Session with a browser UA. Warm cookies + spacing pass
    Reddit's rate limiter that 429s cold back-to-back requests."""
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept": "application/atom+xml, application/xml, text/xml, */*"})
    return s


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return (head.startswith("<!doctype html") or head.startswith("<html")
            or "<head" in head or "theme-beta" in head)


def _request(session, url, *, params=None, sleep=time.sleep):
    """GET with retry/backoff. Returns response text, or None on hard failure.

    Retries on 429 (rate limit), 5xx, network errors, and HTML challenge pages.
    A non-retryable non-200 (e.g. 404) returns None immediately. Never raises.
    """
    for attempt, backoff in enumerate((0.0,) + _RETRY_BACKOFF_S):
        if backoff:
            sleep(backoff)
        try:
            resp = session.get(url, params=params, timeout=30)
        except Exception as exc:
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
            logger.warning("Reddit %s returned an HTML/challenge page — retry (attempt %d)",
                           url, attempt)
            continue
        return text
    logger.error("Reddit %s failed after retries — failing open (0 items).", url)
    return None


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return " ".join(text.split())


def _extract_link_meta(content_html: str, permalink: str):
    """Best-effort (is_self, domain) from a Reddit Atom entry's content HTML.

    Reddit entry content carries a '[link]' anchor pointing at the submission URL
    (== the permalink for self-posts, an external URL otherwise). Degrades to
    (None, "") when the structure isn't present — metrics are optional in RSS mode.
    """
    try:
        from urllib.parse import urlparse
        hrefs = re.findall(r'href="([^"]+)"', content_html or "")
        for h in hrefs:
            if "/comments/" in h:   # the permalink / [comments] anchor — skip
                continue
            host = urlparse(h).netloc.lower()
            if not host:
                continue
            if "reddit.com" in host:
                return True, ""      # submission points back into reddit → self
            return False, host       # external link-out
    except Exception:
        pass
    return None, ""


def _parse_date(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(t.tm_year, t.tm_mon, t.tm_mday,
                                tzinfo=timezone.utc).strftime("%Y-%m-%d")
            except Exception:
                pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fetch_rss(config: dict, *, session, sleep) -> list[dict]:
    import feedparser

    subreddits = config.get("subreddits", []) or []
    top_n = int(config.get("top_n_per_sub", 5))
    time_filter = str(config.get("time_filter", "week"))
    delay = float(config.get("request_delay_s", 3.0))

    results: list[dict] = []
    seen_urls: set[str] = set()

    for idx, sub in enumerate(subreddits):
        if idx > 0 and delay > 0:
            sleep(delay)   # space requests — Reddit 429s cold back-to-back RSS
        url = f"{_BASE}/r/{sub}/top/.rss"
        text = _request(session, url, params={"t": time_filter}, sleep=sleep)
        if text is None:
            continue  # fail-open: this sub contributes nothing
        parsed = feedparser.parse(text)
        if parsed.get("bozo") and not parsed.get("entries"):
            logger.warning("Reddit r/%s RSS parse error: %s", sub,
                           parsed.get("bozo_exception", "unknown"))
            continue

        kept = 0
        for rank, entry in enumerate(parsed.get("entries", [])):
            permalink = entry.get("link", "")
            if not permalink or permalink in seen_urls:
                continue
            seen_urls.add(permalink)

            content_html = ""
            if entry.get("content"):
                content_html = entry["content"][0].get("value", "")
            elif entry.get("summary"):
                content_html = entry.get("summary", "")
            body = _strip_html(content_html)[:500] or f"Posted in r/{sub}."
            is_self, domain = _extract_link_meta(content_html, permalink)

            flair = ""
            raw_tags = [sub]
            for tag in entry.get("tags", []) or []:
                term = tag.get("term", "")
                if term and term.lower() != sub.lower():
                    flair = term
                    raw_tags.append(term.lower().replace(" ", "-"))
                    break

            results.append({
                "source": f"Reddit/r/{sub}",
                "source_url": permalink,
                "title": entry.get("title", "(no title)"),
                "body": body,
                "published_date": _parse_date(entry),
                "raw_tags": raw_tags,
                # Wire dict — full shape; RSS lacks engagement metrics, so those
                # default to 0 with metrics_available=False (the funnel handles it).
                "wire": {
                    "subreddit": sub,
                    "score": 0,
                    "num_comments": 0,
                    "upvote_ratio": 0.0,
                    "is_video": False,
                    "is_self": bool(is_self) if is_self is not None else False,
                    "domain": domain,
                    "flair": flair,
                    "permalink": permalink.replace(_BASE, ""),
                    "feed_rank": rank,            # Reddit's own top-sort position
                    "metrics_available": False,   # RSS mode: no score/comments/ratio
                },
            })
            kept += 1
            if kept >= top_n:
                break
        logger.info("Reddit r/%s: kept %d of %d (RSS top/.rss?t=%s)",
                    sub, kept, len(parsed.get("entries", [])), time_filter)

    return results


# ── Legacy unauthenticated .json path (Reddit-blocked; kept for reference) ────
# Reddit returns 403 for unauthenticated .json listing access. This parser is
# retained only as the shape an authenticated (oauth.reddit.com) transport would
# return, should an OAuth path ever be added. It is NOT reachable in RSS mode.
def _parse_listing(payload, subreddit_name):
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
        body = (selftext[:500] if selftext
                else f"Posted in r/{subreddit_name} with {score} upvotes.")
        try:
            published_date = datetime.fromtimestamp(
                float(d.get("created_utc", 0)), tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            published_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        flair = (d.get("link_flair_text") or "")
        raw_tags = [subreddit_name] + ([flair.lower().replace(" ", "-")] if flair else [])
        out.append({
            "source": f"Reddit/r/{subreddit_name}", "source_url": permalink,
            "title": d.get("title", ""), "body": body,
            "published_date": published_date, "raw_tags": raw_tags,
            "wire": {
                "subreddit": subreddit_name, "score": score,
                "num_comments": int(d.get("num_comments", 0) or 0),
                "upvote_ratio": float(d.get("upvote_ratio", 0.0) or 0.0),
                "is_video": bool(d.get("is_video", False)),
                "is_self": bool(d.get("is_self", False)),
                "domain": d.get("domain", ""), "flair": flair,
                "permalink": d.get("permalink", ""), "metrics_available": True,
            },
        })
    return out


def fetch(config: dict, *, session=None, sleep=time.sleep) -> list[dict]:
    """Fetch top-N-per-sub weekly posts (Stage 0). RSS by default.

    ``session``/``sleep`` are injectable for hermetic testing; in production both
    default to a live session and real sleep.
    """
    if session is None:
        session = _new_session()
    access = str(config.get("access", "rss")).lower()
    if access == "json":
        logger.warning("Reddit access=json is blocked by Reddit (403). "
                       "Falling back to RSS. Set access: rss in the config.")
    return _fetch_rss(config, session=session, sleep=sleep)


def fetch_comments(permalink_path: str, *, session=None, sleep=time.sleep,
                   top_k: int = 12) -> list[str]:
    """Stage-3 deep-dive (unavailable in RSS mode — comment .json is 403-blocked).

    Retained for a future authenticated transport. Returns [] under RSS access,
    so run_funnel's deep-dive is a safe no-op when funnel.deep_dive is false.
    """
    return []
