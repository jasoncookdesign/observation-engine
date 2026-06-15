"""
Vault writer for the Music Culture Observation Engine.
Writes processed observations as Markdown notes to the Obsidian vault.
"""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def write(observation: dict, output_config: dict) -> str:
    """
    Write a processed observation to the vault inbox.

    Args:
        observation: Processed observation dict (from processor.py).
                     Expected keys: source, source_url, date, observation,
                     tags, interest_level, lenses, questions, expanded_context.
        output_config: The 'output' section of the instance config.
                       Expected keys: vault_path, inbox_folder.

    Returns:
        Absolute path to the written file.

    Raises:
        OSError: If the file cannot be written.
    """
    vault_path = Path(output_config["vault_path"])
    inbox_folder = output_config.get("inbox_folder", "Observation Inbox")
    inbox_path = vault_path / inbox_folder
    inbox_path.mkdir(parents=True, exist_ok=True)

    filename = _make_filename(observation)
    file_path = inbox_path / filename

    content = _render_note(observation)

    file_path.write_text(content, encoding="utf-8")
    logger.info("Written: %s", file_path)
    return str(file_path)


def _make_filename(observation: dict) -> str:
    """
    Generate filename: {date}-{source_slug}-{4char_hash}.md
    Hash is derived from source_url to ensure stability.
    """
    date_str = observation.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    source = observation.get("source", "unknown")
    source_url = observation.get("source_url", source)

    # Slug: first word(s) of source, lowercased, alphanum only
    source_slug = _slugify(source)[:8]

    # 4-char hash from source_url
    url_hash = hashlib.md5(source_url.encode("utf-8")).hexdigest()[:4]

    return f"{date_str}-{source_slug}-{url_hash}.md"


def _slugify(text: str) -> str:
    """Convert source name to a filesystem-safe slug."""
    import re
    # Take first meaningful word(s), strip non-alphanum
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "src"


def _render_note(obs: dict) -> str:
    """Render a complete Obsidian Markdown note from a processed observation."""
    date_str = obs.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    source = obs.get("source", "")
    source_url = obs.get("source_url", "")
    observation_text = obs.get("observation", "")
    tags = obs.get("tags", [])
    interest_level = obs.get("interest_level", 1)
    lenses = obs.get("lenses", [])
    questions = obs.get("questions", {})
    expanded_context = obs.get("expanded_context", "")

    # Build note ID
    source_slug = _slugify(source)[:8]
    url_hash = hashlib.md5(source_url.encode("utf-8")).hexdigest()[:4]
    note_id = f"{date_str}-{source_slug}-{url_hash}"

    # YAML frontmatter — build as an ordered string to control formatting
    frontmatter_lines = [
        "---",
        f"id: {note_id}",
        f"date: {date_str}",
        f"source: {_yaml_str(source)}",
        f"source_url: {_yaml_str(source_url)}",
        f"observation: {_yaml_str(observation_text)}",
        f"tags: [{', '.join(tags)}]",
        f"interest_level: {interest_level}",
        f"lenses: [{', '.join(lenses)}]",
        "status: inbox",
        'notes: ""',
        "---",
    ]
    frontmatter = "\n".join(frontmatter_lines)

    # Body
    source_line = f"[{source}]({source_url})" if source_url else source
    body_parts = ["## Observation", "", expanded_context or observation_text, "", f"**Source:** {source_line}", "", "## Questions"]

    for lens_name in lenses:
        lens_questions = questions.get(lens_name, [])
        if lens_questions:
            body_parts.append(f"\n### {lens_name}")
            for q in lens_questions:
                body_parts.append(f"- {q}")

    body = "\n".join(body_parts)

    return frontmatter + "\n\n" + body + "\n"


def _yaml_str(value: str) -> str:
    """Quote a string for safe inline YAML embedding."""
    if not value:
        return '""'
    # Normalise: collapse newlines to spaces
    value = value.replace('\r', '').replace('\n', ' ').strip()
    # Always double-quote: escape backslashes and double-quotes inside
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def list_existing_urls(output_config: dict) -> set[str]:
    """
    Read existing vault inbox notes and return a set of source_urls already written.
    Used by main.py to deduplicate across runs.
    """
    vault_path = Path(output_config["vault_path"])
    inbox_folder = output_config.get("inbox_folder", "Observation Inbox")
    inbox_path = vault_path / inbox_folder

    existing_urls: set[str] = set()

    if not inbox_path.exists():
        return existing_urls

    for md_file in inbox_path.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            # Extract source_url from frontmatter
            if content.startswith("---"):
                end = content.find("---", 3)
                if end > 0:
                    fm_text = content[3:end]
                    fm = yaml.safe_load(fm_text)
                    if isinstance(fm, dict) and fm.get("source_url"):
                        existing_urls.add(fm["source_url"])
        except Exception as exc:
            logger.debug("Could not read existing note %s: %s", md_file, exc)

    return existing_urls
