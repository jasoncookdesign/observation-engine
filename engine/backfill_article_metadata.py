"""Backfill INI-138 article metadata into existing observation notes.

Only YAML frontmatter is replaced. Markdown bodies are preserved byte-for-byte
after the closing frontmatter delimiter.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import yaml

from article_metadata import build


def _split(text: str) -> tuple[str, str] | None:
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end < 0:
        return None
    return text[3:end], text[end + 3:]


def _observation_text(body: str) -> str:
    """Keep factual observation prose; exclude source and generated questions."""
    text = body.split("## Observation", 1)[-1]
    text = text.split("**Source:**", 1)[0]
    text = text.split("## Questions", 1)[0]
    return text.strip()


def _backfill(path: Path, write: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    parts = _split(text)
    if not parts:
        return False
    fm_text, body = parts
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(fm, dict):
        return False
    observation = fm.get("observation", "")
    metadata = build(
        {
            "note_id": fm.get("id", path.stem),
            "title": fm.get("title") or observation,
            "source": fm.get("source", ""),
            "source_url": fm.get("source_url", ""),
            "published_date": fm.get("date", ""),
            "raw_tags": fm.get("tags", []),
        },
        {
            "observation": observation,
            "expanded_context": _observation_text(body),
            "tags": fm.get("tags", []),
        },
    )
    fm.update({
        "note_id": metadata["note_id"], "title": metadata["title"],
        "publication": metadata["publication"],
        "publication_date": metadata["publication_date"],
        "author": metadata["author"], "topics": metadata["topics"],
        "entities": metadata["entities"], "summary": metadata["summary"],
        "claims": metadata["claims"], "relevance": metadata["relevance"],
        "time_sensitivity": metadata["time_sensitivity"],
    })
    if write:
        rendered = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip() + "\n---" + body
        fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
    return True


def backfill(vault: Path, write: bool = False) -> dict:
    # Only observation-engine output is in scope. Reel Treatments, lenses, and
    # other client-authored surfaces have different frontmatter contracts.
    candidates = sorted(
        list((vault / "Observation Inbox").glob("*.md"))
        + list((vault / "Archived").glob("*.md"))
    )
    changed = [p for p in candidates if _backfill(p, write=write)]
    return {"candidates": len(candidates), "changed": len(changed), "paths": [str(p) for p in changed]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = backfill(args.vault, write=args.write)
    print(f"{'updated' if args.write else 'would update'} {result['changed']} of {result['candidates']} markdown notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
