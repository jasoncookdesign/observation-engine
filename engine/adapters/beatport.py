"""
Beatport adapter for the Music Culture Observation Engine.
Scrapes Beatport genre chart pages using requests + BeautifulSoup.
"""

import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CHART_URL = "https://www.beatport.com/genre/{slug}/top-100"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20


def fetch(config: dict) -> list[dict]:
    """
    Scrape top-N tracks from each Beatport genre chart in config['charts'].

    Args:
        config: The 'beatport' section of the instance config YAML.
                Expected keys:
                  charts (list of {genre, slug})
                  top_n (int)

    Returns:
        List of raw observation dicts. Empty list on complete failure.
    """
    results = []
    charts = config.get("charts", [])
    top_n = int(config.get("top_n", 10))

    for chart_def in charts:
        genre = chart_def.get("genre", "Unknown Genre")
        slug = chart_def.get("slug", "")
        if not slug:
            logger.warning("Beatport chart '%s' has no slug — skipping.", genre)
            continue

        chart_url = CHART_URL.format(slug=slug)

        try:
            tracks = _scrape_chart(chart_url, genre, slug, top_n)
            results.extend(tracks)
        except Exception as exc:
            logger.error(
                "Beatport scrape error for '%s' (%s): %s", genre, chart_url, exc
            )
            continue

    return results


def _scrape_chart(
    chart_url: str, genre: str, genre_slug: str, top_n: int
) -> list[dict]:
    """Scrape a single Beatport chart page and return observation dicts."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    # Prime the session with a homepage request to pick up Cloudflare cookies
    try:
        session.get("https://www.beatport.com/", timeout=REQUEST_TIMEOUT)
    except Exception:
        pass
    response = session.get(chart_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    tracks = []
    seen: set[str] = set()

    # Beatport renders tracks in a Next.js __NEXT_DATA__ JSON blob as well as
    # in the HTML. Try HTML selectors first; fall back to JSON extraction.
    tracks = _extract_from_html(soup, genre, genre_slug, chart_url, today, top_n)

    if not tracks:
        tracks = _extract_from_next_data(
            soup, genre, genre_slug, chart_url, today, top_n
        )

    return tracks


def _extract_from_html(
    soup: BeautifulSoup,
    genre: str,
    genre_slug: str,
    chart_url: str,
    today: str,
    top_n: int,
) -> list[dict]:
    """Attempt HTML-selector extraction of track listings."""
    results = []

    # Common Beatport track row selectors (may change with site updates)
    track_elements = soup.select(
        "li.bucket-item, li[class*='track'], div[class*='track-row']"
    )

    if not track_elements:
        # Try generic list items that contain artist + title patterns
        track_elements = soup.select("ol.bucket-items > li, ul.tracks > li")

    for i, element in enumerate(track_elements[:top_n]):
        try:
            artist = _extract_text(
                element,
                [
                    ".artists",
                    ".track-artists",
                    "[class*='artist']",
                    "span.artists",
                ],
            )
            title = _extract_text(
                element,
                [
                    ".title",
                    ".track-title",
                    "[class*='title']",
                    "span.name",
                ],
            )

            if not artist and not title:
                continue

            label = f"{artist} — {title}" if artist and title else (artist or title)
            key = label.lower()
            if key in {r["title"].lower() for r in results}:
                continue

            results.append(
                _make_observation(label, genre, genre_slug, chart_url, today)
            )
        except Exception as exc:
            logger.debug("HTML extraction error on element %d: %s", i, exc)
            continue

    return results


def _extract_from_next_data(
    soup: BeautifulSoup,
    genre: str,
    genre_slug: str,
    chart_url: str,
    today: str,
    top_n: int,
) -> list[dict]:
    """Extract track data from Next.js __NEXT_DATA__ JSON embedded in page."""
    import json

    results = []
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script_tag:
        return results

    try:
        data = json.loads(script_tag.string)
    except Exception as exc:
        logger.debug("__NEXT_DATA__ JSON parse error: %s", exc)
        return results

    # Walk the nested structure looking for track lists
    tracks_data = _find_tracks_in_json(data)

    for item in tracks_data[:top_n]:
        try:
            title = item.get("name", item.get("title", ""))
            artists = item.get("artists", [])
            if isinstance(artists, list):
                artist_names = ", ".join(
                    a.get("name", "") for a in artists if a.get("name")
                )
            else:
                artist_names = str(artists)

            label = (
                f"{artist_names} — {title}"
                if artist_names and title
                else (title or artist_names)
            )
            if not label:
                continue

            results.append(
                _make_observation(label, genre, genre_slug, chart_url, today)
            )
        except Exception as exc:
            logger.debug("JSON track extraction error: %s", exc)
            continue

    return results


def _find_tracks_in_json(data, depth: int = 0) -> list:
    """Recursively search JSON structure for a list of track objects."""
    if depth > 10:
        return []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        if "name" in data[0] or "title" in data[0]:
            return data
    if isinstance(data, dict):
        for key in ("tracks", "items", "results", "data"):
            if key in data:
                result = _find_tracks_in_json(data[key], depth + 1)
                if result:
                    return result
        for value in data.values():
            result = _find_tracks_in_json(value, depth + 1)
            if result:
                return result
    return []


def _extract_text(element, selectors: list[str]) -> str:
    """Try multiple CSS selectors, return first match's text."""
    for selector in selectors:
        el = element.select_one(selector)
        if el:
            return el.get_text(strip=True)
    return ""


def _make_observation(
    label: str, genre: str, genre_slug: str, chart_url: str, today: str
) -> dict:
    return {
        "source": "Beatport Charts",
        "source_url": chart_url,
        "title": label,
        "body": f"Track charting in Beatport {genre} Top 100.",
        "published_date": today,
        "raw_tags": [genre_slug, "chart", "beatport"],
    }
