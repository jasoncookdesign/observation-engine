"""
RSS adapter for the Music Culture Observation Engine.
Fetches entries from configured RSS/Atom feeds using feedparser.
"""

import logging
from datetime import datetime, timezone

import feedparser

logger = logging.getLogger(__name__)

BODY_MAX_CHARS = 500


def fetch(config: dict) -> list[dict]:
    """
    Fetch raw observations from all RSS feeds in config['feeds'].

    Args:
        config: The 'rss' section of the instance config YAML.
                Expected keys: feeds (list of {name, url, slug})

    Returns:
        List of raw observation dicts. Empty list on complete failure.
    """
    results = []
    feeds = config.get("feeds", [])

    for feed_def in feeds:
        name = feed_def.get("name", "Unknown Feed")
        url = feed_def.get("url", "")
        slug = feed_def.get("slug", "rss")

        if not url:
            logger.warning("Feed '%s' has no URL — skipping.", name)
            continue

        try:
            parsed = feedparser.parse(url)
        except Exception as exc:
            logger.error("feedparser error for '%s' (%s): %s", name, url, exc)
            continue

        if parsed.get("bozo") and not parsed.get("entries"):
            logger.warning(
                "Feed '%s' returned bozo error: %s",
                name,
                parsed.get("bozo_exception", "unknown"),
            )
            continue

        seen_urls: set[str] = set()

        for entry in parsed.get("entries", []):
            try:
                source_url = entry.get("link", "")
                if not source_url or source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                title = entry.get("title", "(no title)")

                # Body: prefer summary, then content
                body = ""
                if entry.get("summary"):
                    body = entry["summary"]
                elif entry.get("content"):
                    body = entry["content"][0].get("value", "")

                # Strip any HTML tags from body (simple approach without lxml dep)
                import re
                body = re.sub(r"<[^>]+>", " ", body)
                body = " ".join(body.split())  # normalise whitespace
                body = body[:BODY_MAX_CHARS]

                # Published date
                published_date = _parse_date(entry)

                # Tags from feed categories
                raw_tags = [
                    tag.get("term", "")
                    for tag in entry.get("tags", [])
                    if tag.get("term")
                ]

                results.append(
                    {
                        "source": name,
                        "source_url": source_url,
                        "title": title,
                        "body": body,
                        "published_date": published_date,
                        "raw_tags": raw_tags,
                    }
                )
            except Exception as exc:
                logger.error(
                    "Error processing entry in feed '%s': %s", name, exc
                )
                continue

    return results


def _parse_date(entry: dict) -> str:
    """Return ISO8601 date string from a feedparser entry, defaulting to today."""
    try:
        if entry.get("published_parsed"):
            t = entry["published_parsed"]
            dt = datetime(t.tm_year, t.tm_mon, t.tm_mday, tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d")
        if entry.get("updated_parsed"):
            t = entry["updated_parsed"]
            dt = datetime(t.tm_year, t.tm_mon, t.tm_mday, tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
