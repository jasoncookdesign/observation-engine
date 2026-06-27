from __future__ import annotations
"""
Relevance funnel for the Observation Engine (INI-100).

A precision-first funnel that surfaces *reaction-worthy* posts, not merely
upvoted ones. Each stage is more expensive than the last and runs only on what
the previous stage earned:

  Stage 1  wire_prerank      free   — score from listing wire metrics, no calls/inference
  Stage 2  triage_gate       cheap  — lens-anchored LLM reaction-worthiness gate (a true gate)
  Stage 3  (deep-dive)       1 call — comment fetch for survivors (engine/adapters/reddit.fetch_comments)
  Stage 4  (existing processor)     — full interest/lens/questions → vault
  Stage 5  harvest_labels    free   — vault status chain → positives + hard negatives → Stage-2 few-shot

Design hedges (INI-100): a "Maybe" overflow bucket so precision tuning never
silently kills a gem, and deliberate hard-negative capture (high-wire-score but
ignored) which teaches the substance/eye-candy boundary better than random negatives.

Stages 1 and 5 are pure (no network, no inference) and unit-tested in-sandbox.
Stage 2 takes an injected ``generate_fn`` (defaults to inference.generate_json)
so the gate logic is testable with a fake model.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Stage 1: wire-metric pre-rank (pure) ─────────────────────────────────────
# Glass-box scoring over listing fields already in hand. Ranks rather than
# hard-cuts (precision priority: borderline gems aren't silently dropped here).

# Content types that are usually passive eye-candy → downweight; text/discussion
# /news/link-out → upweight. Tunable; this is the substance/eye-candy prior.
_PASSIVE_DOMAINS = ("i.redd.it", "v.redd.it", "i.imgur.com", "imgur.com",
                    "gfycat.com", "youtube.com", "youtu.be")


def wire_score(item: dict, taxonomy=None) -> float:
    """Reaction-worthiness PRIOR from wire metrics only. Higher = more promising.

    The comments-to-score ratio is the key eye-candy discriminator: passive
    content accrues upvotes but thin discussion. We reward discussion density,
    text/self posts and news link-outs, and a title hit against the CEO's
    interest taxonomy; we penalise passive video/image domains.
    """
    w = item.get("wire", {})
    score = max(int(w.get("score", 0)), 0)
    num_comments = max(int(w.get("num_comments", 0)), 0)
    upvote_ratio = float(w.get("upvote_ratio", 0.0) or 0.0)

    # Discussion density — comments per upvote, the eye-candy discriminator.
    # Normalised with a soft cap so a single viral thread can't dominate.
    density = num_comments / (score + 10.0)
    density_component = min(density, 1.0) * 5.0

    # Content type prior.
    type_component = 0.0
    if w.get("is_self"):
        type_component += 2.0          # text / discussion
    if w.get("is_video"):
        type_component -= 1.5          # passive visual
    domain = (w.get("domain") or "").lower()
    if any(d in domain for d in _PASSIVE_DOMAINS):
        type_component -= 1.0
    elif domain and not domain.startswith("self."):
        type_component += 1.0          # external article / news link-out

    # Consensus quality — a high upvote_ratio means non-controversial signal;
    # mild reward, not dominant (controversy can be reaction-worthy too).
    ratio_component = (upvote_ratio - 0.5) * 2.0

    # Taxonomy title match (CEO interest keywords).
    tax_component = 0.0
    if taxonomy:
        title = (item.get("title", "") or "").lower()
        hits = sum(1 for kw in taxonomy if kw.lower() in title)
        tax_component = min(hits, 3) * 1.5

    # A small log-scaled popularity term keeps total ordering sane without
    # letting raw upvotes dominate (the whole point of the funnel).
    import math
    pop_component = math.log10(score + 1)

    return round(density_component + type_component + ratio_component
                 + tax_component + pop_component, 4)


def wire_prerank(items, taxonomy=None):
    """Attach ``wire_pre_score`` to each item and return them sorted desc. Pure."""
    for it in items:
        it["wire_pre_score"] = wire_score(it, taxonomy)
    return sorted(items, key=lambda it: it["wire_pre_score"], reverse=True)


# ── Stage 2: lens-anchored LLM triage gate ───────────────────────────────────
_TRIAGE_SYSTEM = """\
You are a precision triage gate for a cultural-intelligence system. You decide
whether a social post is worth a deeper, expensive look — NOT whether it is
popular. A post is reaction-worthy when it gives at least one interpretive lens
real purchase: the operator has a frame to react THROUGH it (a take, a video, a
blog). Festival clips, gear-porn, and pure eye-candy are NOT reaction-worthy even
when highly upvoted. Be selective. Output JSON only.

LENS LIBRARY (the frames a post can earn purchase through):
{lens_summary}
"""

_TRIAGE_USER = """\
{exemplar_block}Post:
  Subreddit: r/{subreddit}
  Title: {title}
  Body: {body}
  Wire: score={score}, comments={num_comments}, upvote_ratio={upvote_ratio}

Score reaction-worthiness 0-5 (0=pure eye-candy/no frame, 5=rich, multi-lens).
Name the single best-fitting lens. Return JSON only:
{{"reaction_worthiness": <int 0-5>, "best_lens": "<lens name>", "why": "<= 20 words"}}
"""


def _format_exemplars(exemplars):
    if not exemplars:
        return ""
    lines = ["Calibration examples (learn the operator's taste):"]
    for ex in exemplars[:8]:
        verdict = "REACTION-WORTHY" if ex.get("positive") else "NOT reaction-worthy (ignored)"
        lines.append(f"- [{verdict}] r/{ex.get('subreddit','?')}: {ex.get('title','')[:120]}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _parse_triage(text):
    t = re.sub(r"^```(?:json)?\s*", "", (text or "").strip(), flags=re.I)
    t = re.sub(r"\s*```$", "", t.strip())
    try:
        obj = json.loads(t)
    except ValueError:
        return None
    try:
        rw = int(obj.get("reaction_worthiness", 0))
    except (TypeError, ValueError):
        return None
    obj["reaction_worthiness"] = max(0, min(5, rw))
    return obj


def triage_gate(items, lens_summary, *, generate_fn, exemplars=None,
                threshold=3, max_survivors=None, maybe_band=1):
    """Stage 2 — a TRUE gate. Only survivors earn a Stage-3 deep-dive.

    For each item, run a cheap lens-anchored inference scoring reaction-worthiness
    0-5. Items scoring >= ``threshold`` survive. Items within ``maybe_band`` below
    the threshold go to the "Maybe" overflow bucket (never silently dropped — a
    gem the CEO fishes out becomes a high-value positive label). ``generate_fn``
    has the signature of inference.generate_json: (system, user) -> (text, backend).

    Returns (survivors, maybe, rejected); each item is annotated with
    ``triage`` (the parsed verdict) and ``triage_score``.
    """
    survivors, maybe, rejected = [], [], []
    exemplar_block = _format_exemplars(exemplars)
    system = _TRIAGE_SYSTEM.format(lens_summary=lens_summary or "(none)")
    for it in items:
        w = it.get("wire", {})
        user = _TRIAGE_USER.format(
            exemplar_block=exemplar_block,
            subreddit=w.get("subreddit", ""),
            title=it.get("title", ""),
            body=(it.get("body", "") or "")[:500],
            score=w.get("score", 0),
            num_comments=w.get("num_comments", 0),
            upvote_ratio=w.get("upvote_ratio", 0.0),
        )
        try:
            text, _backend = generate_fn(system, user)
        except Exception as exc:
            # Fail-open: if triage inference errors, treat as Maybe (don't drop).
            logger.warning("Triage inference error: %s — routing to Maybe", exc)
            it["triage"] = {"reaction_worthiness": threshold - 1, "error": str(exc)}
            it["triage_score"] = threshold - 1
            maybe.append(it)
            continue
        verdict = _parse_triage(text) or {"reaction_worthiness": 0, "why": "unparsable"}
        it["triage"] = verdict
        it["triage_score"] = verdict["reaction_worthiness"]
        if verdict["reaction_worthiness"] >= threshold:
            survivors.append(it)
        elif verdict["reaction_worthiness"] >= threshold - maybe_band:
            maybe.append(it)
        else:
            rejected.append(it)

    survivors.sort(key=lambda it: it["triage_score"], reverse=True)
    if max_survivors is not None:
        overflow = survivors[max_survivors:]
        survivors = survivors[:max_survivors]
        maybe = overflow + maybe   # budget overflow joins Maybe, not the bin
    return survivors, maybe, rejected


# ── Stage 5: feedback label harvest (pure read of the vault status chain) ─────
# The vault `status` frontmatter chain (inbox → queued → reacted → archived) is
# a labeled dataset. Posts the CEO reacted to are positives; high-wire-score
# posts that aged out untouched are the instructive HARD negatives.

_REACTED_STATES = {"reacted", "queued", "published", "posted"}
_IGNORED_STATES = {"archived", "ignored", "skipped"}


def _read_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


def harvest_labels(vault_path, *, reddit_only=True):
    """Walk the vault and label observations from their status chain.

    Returns {"positives": [...], "negatives": [...]} where each entry is
    {title, subreddit, source_url, status, positive}. A Reddit source_url yields
    the subreddit; non-Reddit items are included only when reddit_only is False.
    """
    positives, negatives = [], []
    root = Path(vault_path)
    if not root.is_dir():
        return {"positives": positives, "negatives": negatives}
    for md in root.rglob("*.md"):
        if "/lenses/" in str(md) or md.name.lower() == "readme.md":
            continue
        try:
            fm = _read_frontmatter(md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        url = fm.get("source_url", "")
        is_reddit = "reddit.com/r/" in url
        if reddit_only and not is_reddit:
            continue
        status = (fm.get("status", "") or "").lower()
        subreddit = ""
        if is_reddit:
            m = re.search(r"reddit\.com/r/([^/]+)/", url)
            subreddit = m.group(1) if m else ""
        entry = {
            "title": fm.get("title", "") or fm.get("observation", ""),
            "subreddit": subreddit,
            "source_url": url,
            "status": status,
        }
        if status in _REACTED_STATES:
            entry["positive"] = True
            positives.append(entry)
        elif status in _IGNORED_STATES:
            entry["positive"] = False
            negatives.append(entry)
    return {"positives": positives, "negatives": negatives}


def select_exemplars(labels, *, n_pos=4, n_neg=4):
    """Most-recent positives + hard negatives for Stage-2 few-shot injection.

    rglob order is filesystem-dependent, so callers that want recency should sort
    upstream; here we simply take the head of each list (the harvest preserves
    discovery order) and cap counts. Returns a flat exemplar list.
    """
    pos = (labels.get("positives") or [])[:n_pos]
    neg = (labels.get("negatives") or [])[:n_neg]
    return pos + neg


# ── Orchestration ────────────────────────────────────────────────────────────
def run_funnel(reddit_items, *, lens_summary, generate_fn, taxonomy=None,
               exemplars=None, threshold=3, max_survivors=None,
               deep_dive_fn=None):
    """Run Stages 1→3 over raw Reddit items; return the items to hand to Stage 4.

    Stage 1 ranks; Stage 2 gates; Stage 3 (optional ``deep_dive_fn(permalink)``)
    enriches survivor bodies with comment signal. The returned survivors + maybe
    items carry their funnel annotations. Survivors are what proceed to the
    existing processor; the Maybe bucket is surfaced separately by the caller.
    """
    ranked = wire_prerank(list(reddit_items), taxonomy)
    survivors, maybe, rejected = triage_gate(
        ranked, lens_summary, generate_fn=generate_fn, exemplars=exemplars,
        threshold=threshold, max_survivors=max_survivors,
    )
    if deep_dive_fn is not None:
        for it in survivors:
            permalink = it.get("wire", {}).get("permalink", "")
            if not permalink:
                continue
            try:
                comments = deep_dive_fn(permalink)
            except Exception as exc:
                logger.warning("Deep-dive failed for %s: %s", permalink, exc)
                comments = []
            if comments:
                joined = " | ".join(comments)
                it["body"] = (it.get("body", "") + "\n\nTop comments: " + joined)[:1500]
                it["deep_dived"] = True
    return {"survivors": survivors, "maybe": maybe, "rejected": rejected}
