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

# Adapter registry — modules are imported lazily so a missing optional
# dependency doesn't break the run when that adapter is disabled.
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

    # --- Reddit relevance funnel (INI-100, Stages 1-3) ---
    # Reddit items carry a `wire` dict; other sources do not. Gate Reddit through
    # the precision funnel so only reaction-worthy survivors reach the processor.
    # Non-Reddit items pass through untouched. Fail-open: any funnel error leaves
    # the original Reddit items in place.
    all_raw, funnel_stats = _apply_reddit_funnel(all_raw, cfg)
    if funnel_stats:
        logger.info(
            "Reddit funnel: %d in → %d survivors, %d maybe, %d rejected.",
            funnel_stats["in"], funnel_stats["survivors"],
            funnel_stats["maybe"], funnel_stats["rejected"],
        )

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


def _apply_reddit_funnel(all_raw: list[dict], cfg: dict):
    """Gate Reddit items through the INI-100 relevance funnel (Stages 1-3).

    Returns (new_all_raw, stats|None). Splits Reddit items (those with a `wire`
    dict) from the rest, runs the funnel, and recombines survivors with the
    non-Reddit items. "Maybe" items are tagged and kept (routed to the vault's
    Maybe bucket downstream); rejected items are dropped. Fail-open: on any error
    the original items are returned unchanged.
    """
    reddit_cfg = cfg.get("sources", {}).get("reddit", {})
    funnel_cfg = reddit_cfg.get("funnel", {}) if isinstance(reddit_cfg, dict) else {}
    if not funnel_cfg.get("enabled", True):
        return all_raw, None

    reddit_items = [it for it in all_raw if it.get("wire")]
    other_items = [it for it in all_raw if not it.get("wire")]
    if not reddit_items:
        return all_raw, None

    try:
        import relevance
        import inference
        import processor as _proc
        from adapters import reddit as _reddit

        vault_path = cfg["output"]["vault_path"]
        lens_dir = Path(vault_path) / cfg.get("lens_library_path", "lenses/")
        lens_summary = _proc._load_lens_summary(lens_dir)

        taxonomy = funnel_cfg.get("interest_taxonomy") or reddit_cfg.get("interest_taxonomy")
        threshold = int(funnel_cfg.get("triage_threshold", 3))
        max_survivors = funnel_cfg.get("max_survivors")
        deep_dive = bool(funnel_cfg.get("deep_dive", True))

        # Stage 5 → Stage 2 few-shot: harvest reacted/ignored labels from the vault.
        labels = relevance.harvest_labels(vault_path)
        exemplars = relevance.select_exemplars(labels)
        logger.info("Funnel few-shot: %d positives, %d hard negatives available.",
                    len(labels["positives"]), len(labels["negatives"]))

        def _gen(system, user):
            return inference.generate_json(system, user, max_tokens=256)

        deep_dive_fn = _reddit.fetch_comments if deep_dive else None
        out = relevance.run_funnel(
            reddit_items, lens_summary=lens_summary, generate_fn=_gen,
            taxonomy=taxonomy, exemplars=exemplars, threshold=threshold,
            max_survivors=max_survivors, deep_dive_fn=deep_dive_fn,
        )
    except Exception as exc:  # fail-open — never let the funnel break the run
        logger.error("Reddit funnel error (%s) — passing Reddit items through ungated.", exc)
        return all_raw, None

    for it in out["maybe"]:
        it.setdefault("raw_tags", []).append("maybe-bucket")
    survivors = out["survivors"] + out["maybe"]   # Maybe kept (tagged), rejected dropped
    stats = {
        "in": len(reddit_items),
        "survivors": len(out["survivors"]),
        "maybe": len(out["maybe"]),
        "rejected": len(out["rejected"]),
    }
    return other_items + survivors, stats


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
