"""
Music Culture Observation Engine — CLI entry point and pipeline runner.

Usage:
    python main.py --config configs/dyson-hope.yaml [--dry-run]
"""

import argparse
import logging
import sys
from pathlib import Path

# Allow running as `python engine/main.py` or `python main.py` from engine/
_engine_dir = Path(__file__).parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))

import config as config_module
import processor
import writer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("observation-engine")

# Adapter registry — modules are imported lazily so a missing dependency
# (e.g. praw) doesn't break the run when that adapter is disabled.
_ADAPTER_MODULES = {
    "rss": "adapters.rss",
    "reddit": "adapters.reddit",
    "beatport": "adapters.beatport",
}


def _load_adapter(name: str):
    import importlib
    module_path = _ADAPTER_MODULES.get(name)
    if not module_path:
        raise ValueError(f"Unknown adapter: {name}")
    return importlib.import_module(module_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Music Culture Observation Engine"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to instance config YAML (e.g. configs/dyson-hope.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and process but do not write to vault.",
    )
    args = parser.parse_args()

    # --- Load config ---
    try:
        cfg = config_module.load(args.config)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Config error: %s", exc)
        sys.exit(1)

    output_cfg = cfg["output"]
    interest_threshold = output_cfg.get("interest_threshold", 2)
    dry_run = args.dry_run

    if dry_run:
        logger.info("DRY RUN — observations will be processed but not written.")

    # --- Load existing source URLs to deduplicate across runs ---
    existing_urls: set[str] = set()
    if not dry_run:
        existing_urls = writer.list_existing_urls(output_cfg)
        logger.info("Found %d existing observations in vault.", len(existing_urls))

    # --- Fetch from all enabled adapters ---
    all_raw: list[dict] = []
    sources_cfg = cfg.get("sources", {})

    for adapter_name in _ADAPTER_MODULES:
        source_cfg = sources_cfg.get(adapter_name, {})
        if not source_cfg.get("enabled", False):
            logger.info("Adapter '%s' is disabled — skipping.", adapter_name)
            continue

        try:
            adapter_module = _load_adapter(adapter_name)
        except ImportError as exc:
            logger.error(
                "Adapter '%s' could not be loaded (missing dependency): %s",
                adapter_name, exc,
            )
            continue

        logger.info("Fetching from adapter: %s", adapter_name)
        try:
            raw_items = adapter_module.fetch(source_cfg)
        except Exception as exc:
            logger.error("Unexpected error from adapter '%s': %s", adapter_name, exc)
            raw_items = []

        logger.info(
            "Adapter '%s' returned %d raw observations.", adapter_name, len(raw_items)
        )
        all_raw.extend(raw_items)

    n_fetched = len(all_raw)
    logger.info("Total raw observations fetched: %d", n_fetched)

    # --- Deduplicate by source_url ---
    seen_this_run: set[str] = set()
    deduped: list[dict] = []

    for item in all_raw:
        url = item.get("source_url", "")
        if not url:
            continue
        if url in existing_urls or url in seen_this_run:
            continue
        seen_this_run.add(url)
        deduped.append(item)

    n_skipped_dedup = n_fetched - len(deduped)
    logger.info(
        "After dedup: %d unique observations (%d skipped as already written).",
        len(deduped),
        n_skipped_dedup,
    )

    # --- Process + write ---
    n_processed = 0
    n_written = 0
    n_skipped_threshold = 0
    n_failed = 0

    for raw_obs in deduped:
        logger.info(
            "Processing: [%s] %s",
            raw_obs.get("source", ""),
            raw_obs.get("title", "")[:80],
        )

        processed = processor.process(raw_obs, cfg)

        if processed is None:
            logger.warning(
                "Processing failed for: %s", raw_obs.get("source_url", "")
            )
            n_failed += 1
            continue

        n_processed += 1

        interest = processed.get("interest_level", 1)
        if interest < interest_threshold:
            logger.info(
                "Skipping (interest_level %d < threshold %d): %s",
                interest,
                interest_threshold,
                raw_obs.get("source_url", ""),
            )
            n_skipped_threshold += 1
            continue

        if dry_run:
            _print_dry_run(processed)
            n_written += 1
        else:
            try:
                written_path = writer.write(processed, output_cfg)
                logger.info("Written: %s", written_path)
                n_written += 1
            except Exception as exc:
                logger.error(
                    "Write error for '%s': %s",
                    processed.get("source_url", ""),
                    exc,
                )
                n_failed += 1

    # --- Summary ---
    action = "would be written" if dry_run else "written"
    print(
        f"\n{'='*60}\n"
        f"  Observation Engine Run Summary\n"
        f"{'='*60}\n"
        f"  Fetched:            {n_fetched}\n"
        f"  Skipped (dedup):    {n_skipped_dedup}\n"
        f"  Processed:          {n_processed}\n"
        f"  Skipped (interest): {n_skipped_threshold}\n"
        f"  {action.capitalize()}: {n_written}\n"
        f"  Failed:             {n_failed}\n"
        f"{'='*60}\n"
    )


def _print_dry_run(obs: dict) -> None:
    """Print a summary of what would be written in dry-run mode."""
    print(
        f"\n[DRY RUN] Would write:\n"
        f"  Source:         {obs.get('source', '')}\n"
        f"  URL:            {obs.get('source_url', '')}\n"
        f"  Observation:    {obs.get('observation', '')}\n"
        f"  Interest Level: {obs.get('interest_level', '')}\n"
        f"  Lenses:         {', '.join(obs.get('lenses', []))}\n"
        f"  Tags:           {', '.join(obs.get('tags', []))}\n"
    )


if __name__ == "__main__":
    main()
