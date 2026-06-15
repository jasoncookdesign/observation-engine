"""
Claude-powered processing agent for the Music Culture Observation Engine.
Transforms raw adapter observations into structured vault-ready dicts.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024

SYSTEM_PROMPT_TEMPLATE = """\
You are an observation processing agent for a cultural intelligence system.

PURPOSE CONTEXT:
{purpose_context}

LENS LIBRARY:
{lens_library_summary}

Your role: receive raw signals, assess relevance, select lenses, generate questions.
You do not create opinions. You surface observations and generate interpretive questions.
"""

PROCESSING_PROMPT_TEMPLATE = """\
Raw observation:
  Source: {source}
  URL: {source_url}
  Title: {title}
  Body: {body}
  Date: {published_date}

Tasks:
1. Write a one-sentence observation summary (factual, no opinion, max 120 chars).
2. Assign 2–5 topic tags (lowercase, hyphenated).
3. Rate interest_level 1–5 (1=generic/low signal, 5=highly relevant to purpose context).
4. Select 1–3 lenses from the Lens Library most applicable to this observation.
5. For each selected lens, generate 2–3 interpretive questions.
6. Write 2–4 sentences of expanded context from the source.

Return as JSON only — no preamble, no commentary:
{{
  "observation": "...",
  "tags": [...],
  "interest_level": <int>,
  "lenses": [...],
  "questions": {{
    "<lens_name>": ["...", "..."],
    ...
  }},
  "expanded_context": "..."
}}
"""


def process(raw: dict, config: dict) -> Optional[dict]:
    """
    Process a single raw observation through the Claude API.

    Args:
        raw: Raw observation dict from an adapter.
             Expected keys: source, source_url, title, body, published_date, raw_tags.
        config: Full instance config dict (from config.py).

    Returns:
        Processed observation dict ready for writer.py, or None on failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error(
            "ANTHROPIC_API_KEY not set — skipping observation: %s",
            raw.get("source_url", ""),
        )
        return None

    purpose_context = config["instance"].get("purpose_context", "").strip()
    vault_path = config["output"]["vault_path"]
    lens_library_rel = config.get("lens_library_path", "lenses/")
    lens_dir = Path(vault_path) / lens_library_rel

    lens_summary = _load_lens_summary(lens_dir)
    available_lens_names = _load_lens_names(lens_dir)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        purpose_context=purpose_context,
        lens_library_summary=lens_summary,
    )

    user_prompt = PROCESSING_PROMPT_TEMPLATE.format(
        source=raw.get("source", ""),
        source_url=raw.get("source_url", ""),
        title=raw.get("title", ""),
        body=raw.get("body", ""),
        published_date=raw.get("published_date", ""),
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        response_text = message.content[0].text.strip()
    except Exception as exc:
        logger.error(
            "Anthropic API error for '%s': %s",
            raw.get("source_url", ""),
            exc,
        )
        return None

    parsed = _parse_response(response_text)
    if parsed is None:
        logger.error(
            "Could not parse API response for '%s'",
            raw.get("source_url", ""),
        )
        return None

    # Validate and clamp interest_level
    interest_level = int(parsed.get("interest_level", 1))
    interest_level = max(1, min(5, interest_level))

    # Validate lenses against known lens names
    raw_lenses = parsed.get("lenses", [])
    valid_lenses = _match_lenses(raw_lenses, available_lens_names)

    # Build the questions dict, scoped to valid lenses
    all_questions = parsed.get("questions", {})
    questions = {
        lens: all_questions.get(lens, [])
        for lens in valid_lenses
        if all_questions.get(lens)
    }

    date_str = raw.get(
        "published_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )

    return {
        "source": raw.get("source", ""),
        "source_url": raw.get("source_url", ""),
        "date": date_str,
        "observation": parsed.get("observation", raw.get("title", ""))[:120],
        "tags": parsed.get("tags", raw.get("raw_tags", [])),
        "interest_level": interest_level,
        "lenses": valid_lenses,
        "questions": questions,
        "expanded_context": parsed.get("expanded_context", ""),
    }


def _load_lens_summary(lens_dir: Path) -> str:
    """
    Read all lens .md files and return a numbered list of name + first sentence
    of description, suitable for prompt injection.
    """
    if not lens_dir.exists():
        logger.warning("Lens directory not found: %s", lens_dir)
        return "(No lenses available.)"

    lens_files = sorted(lens_dir.glob("*.md"))
    lines = []

    for i, lens_file in enumerate(lens_files, start=1):
        try:
            content = lens_file.read_text(encoding="utf-8")
            name, first_sentence = _parse_lens_note(content)
            if name:
                lines.append(f"{i}. {name}: {first_sentence}")
        except Exception as exc:
            logger.debug("Could not read lens file %s: %s", lens_file, exc)

    return "\n".join(lines) if lines else "(No lenses available.)"


def _load_lens_names(lens_dir: Path) -> List[str]:
    """Return a list of all lens names from the vault's lens directory."""
    if not lens_dir.exists():
        return []

    names = []
    for lens_file in sorted(lens_dir.glob("*.md")):
        try:
            content = lens_file.read_text(encoding="utf-8")
            name, _ = _parse_lens_note(content)
            if name:
                names.append(name)
        except Exception:
            pass
    return names


def _parse_lens_note(content: str) -> tuple[str, str]:
    """
    Extract the lens name from YAML frontmatter and the first sentence of
    the body description.

    Returns:
        (name, first_sentence) — both strings, empty strings on failure.
    """
    import re

    name = ""
    first_sentence = ""

    # Extract name from frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            fm_text = content[3:end]
            for line in fm_text.splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break

    # First sentence of prose body (after any headings)
    body = content[content.find("---", 3) + 3:] if "---" in content[3:] else content
    # Remove heading lines
    body = re.sub(r"^#+.*$", "", body, flags=re.MULTILINE)
    body = body.strip()
    # Take first sentence
    match = re.match(r"([^.!?]+[.!?])", body)
    if match:
        first_sentence = match.group(1).strip()

    return name, first_sentence


def _parse_response(response_text: str) -> Optional[dict]:
    """Parse JSON from Claude's response, handling markdown code fences."""
    import re
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", response_text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.debug("JSON decode error: %s\nResponse: %s", exc, response_text[:300])
        return None


def _match_lenses(raw_lenses: List[str], available: List[str]) -> List[str]:
    """
    Match model-returned lens names against the known available lens names.
    Accepts exact match or case-insensitive match. Returns up to 3.
    """
    available_lower = {name.lower(): name for name in available}
    matched = []
    for raw in raw_lenses:
        canonical = available_lower.get(raw.lower())
        if canonical and canonical not in matched:
            matched.append(canonical)
        if len(matched) >= 3:
            break

    # If no matches, fall back to first lens as a safety default
    if not matched and available:
        matched = [available[0]]

    return matched
