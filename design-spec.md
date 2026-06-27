# Music Culture Observation Engine: Design Spec

**Date:** 2026-06-15

---

## 1. Observation Note Schema

Each processed observation is written to the Obsidian vault as a Markdown file with YAML frontmatter.

### Frontmatter Fields

```yaml
---
id: <ISO8601-date>-<source-slug>-<4char-hash>        # unique identifier, e.g. 2026-06-15-ra-a3f1
date: <YYYY-MM-DD>                                     # observation date
source: <source name>                                  # e.g. "Resident Advisor", "Reddit/r/techno"
source_url: <url>                                      # direct link to original content
observation: <one-sentence summary of the observation> # the signal, not an opinion
tags: [<tag1>, <tag2>]                                 # topic tags: genre, format, business, etc.
interest_level: <1-5>                                  # 1=low signal, 5=high relevance
lenses: [<lens_name>, ...]                             # 1–3 lenses from the Lens Library
status: inbox                                          # inbox | queued | reacted | archived
notes: ""                                              # filled in by the vault owner
---
```

### Body

```markdown
## Observation

<Expanded context from the source — 2–4 sentences, factual. No opinion.>

## Questions

### <Lens Name 1>
- <Question 1>
- <Question 2>

### <Lens Name 2>
- <Question 3>
- <Question 4>
```

### Filename Convention

`<YYYY-MM-DD>-<source-slug>-<4char-hash>.md`

Example: `2026-06-15-ra-a3f1.md`

---

## 2. Adapter Interface Spec

Every source adapter is a Python module that exposes a single function:

```python
def fetch(config: dict) -> list[dict]:
    """
    Fetch raw observations from the source.

    Args:
        config: The adapter's section from the instance config YAML.
                Must include at least 'enabled: true'.

    Returns:
        List of raw observation dicts, each containing:
          - source (str): Human-readable source name
          - source_url (str): Direct URL to the item
          - title (str): Headline or title of the item
          - body (str): Summary/excerpt (200–500 chars preferred)
          - published_date (str): ISO8601 date string
          - raw_tags (list[str]): Any tags/categories from the source
    """
```

### Adapter Contract

- Returns an empty list `[]` on fetch failure (never raises); logs the error internally.
- Never returns duplicate items within a single fetch call.
- Does not process, score, or interpret — raw signal only.
- Adapter is independently importable and testable.
- Adapter file: `adapters/<source_slug>.py`

---

## 3. Instance Config Format

The instance config is a YAML file that drives the engine for one deployment. Engine core reads this file at startup; no instance-specific values appear in engine code.

```yaml
# dyson-hope.yaml — example instance config

instance:
  name: dyson-hope-music-culture
  purpose_context: |
    Dyson Hope is a DJ, producer, and music educator based in [location].
    This observation engine monitors music culture to surface signals relevant
    to his creative practice, content output, and artistic positioning.
    Focus: electronic music culture, DJ/producer ecosystem, music technology,
    underground vs. mainstream dynamics, and scene community.

lens_library_path: lenses/           # relative to vault root; one .md per lens

sources:
  rss:
    enabled: true
    feeds:
      - name: "Resident Advisor"
        url: "https://ra.co/xml/ra.xml"
        slug: "ra"
      - name: "DJ Mag"
        url: "https://djmag.com/feed"
        slug: "djmag"

  reddit:
    enabled: false     # DARK — no viable access path (see Key Decisions); funnel dormant
    # access: rss      # last-attempted mode; inert while disabled
    subreddits:        # the live set (see configs/dyson-hope.yaml for the tuned list)
      - ableton
      - musicproduction
      - edmproduction
      - aves
      - electronicmusic
      - breakbeat
      - DJs
    time_filter: "week"     # top/.rss window (feed is pre-sorted by top)
    top_n_per_sub: 5        # keep best-N per sub (feed order)
    request_delay_s: 3      # spacing between sub feeds (Reddit 429s cold bursts)
    funnel:                 # precision relevance funnel (see relevance.py)
      enabled: true
      triage_threshold: 3   # reaction-worthiness 0-5; >=3 survives
      deep_dive: false      # Stage-3 comment deep-dive needs .json (403-blocked)

  beatport:
    enabled: false     # Cloudflare 403 — requires browser automation or official API key
    charts:
      - genre: "Techno (Raw / Deep / Hypnotic)"
        slug: "techno-raw-deep-hypnotic"
      - genre: "House"
        slug: "house"
      - genre: "Melodic House & Techno"
        slug: "melodic-house-techno"
      - genre: "Organic House / Downtempo"
        slug: "organic-house-downtempo"
    top_n: 10              # tracks to pull per chart

output:
  vault_path: "/path/to/obsidian-vault/dyson-hope-music-culture/"
  inbox_folder: "Observation Inbox"
  interest_threshold: 2   # minimum interest_level to write to vault

schedule:
  cron: "0 8 * * *"       # 08:00 daily
```

---

## 4. Obsidian Vault Structure

```
dyson-hope/                          # vault root
├── .obsidian/
│   └── community-plugins/
│       └── dataview/                # Dataview plugin (must be installed manually)
├── lenses/                          # Lens Library — one note per lens
│   ├── 01-historical-context.md
│   ├── 02-why-this-matters.md
│   ├── ... (18 total)
├── Observation Inbox/               # all new observations land here
│   └── <YYYY-MM-DD>-<source>-<hash>.md
├── Reaction Queue/                  # copy/move here when status = queued
│   └── ...
├── Archived/                        # archived observations
├── Views/
│   ├── Observation Inbox.md         # Dataview query: all inbox observations
│   └── Reaction Queue.md            # Dataview query: status = queued
└── README.md                        # vault orientation for the instance owner
```

### Dataview: Observation Inbox View

```dataview
TABLE date, source, observation, interest_level, lenses, status
FROM "Observation Inbox"
WHERE status = "inbox"
SORT interest_level DESC, date DESC
```

### Dataview: Reaction Queue View

```dataview
TABLE date, source, observation, lenses, notes
FROM "Observation Inbox" OR "Reaction Queue"
WHERE status = "queued"
SORT date DESC
```

---

## 5. Processing Prompt Design

The processing agent receives raw observations from adapters and transforms them into structured vault notes. All prompts are parameterized via the instance config — no hardcoded subject references appear in engine code.

### System Prompt (parameterized)

```
You are an observation processing agent for a cultural intelligence system.

PURPOSE CONTEXT:
{purpose_context}

LENS LIBRARY:
{lens_library_summary}

Your role: receive raw signals, assess relevance, select lenses, generate questions.
You do not create opinions. You surface observations and generate interpretive questions.
```

### Observation Processing Prompt

```
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

Return as JSON:
{
  "observation": "...",
  "tags": [...],
  "interest_level": <int>,
  "lenses": [...],
  "questions": {
    "<lens_name>": ["...", "..."],
    ...
  },
  "expanded_context": "..."
}
```

### Lens Library Injection

The lens library is summarized as a list of `name: one-line description` entries for prompt injection. Full lens notes live in the vault for the instance owner's reference — only the summary is injected into the prompt.

---

## 6. Repository Layout

```
observation-engine/
├── design-spec.md           # this document
├── DOCS.md                  # documentation index
├── INSTALL.md               # macOS deployment guide
├── README.md                # project overview and quick-start
├── requirements.txt         # Python dependencies
├── run.sh                   # launchd launcher (copied to ~/bin at deploy time)
├── com.jasonos.observation-engine.dyson-hope.plist   # launchd schedule template
├── jasonos-observation-engine-activate.command        # one-step activation script
├── engine/
│   ├── main.py              # CLI entry point + pipeline runner
│   ├── config.py            # config loader + validator
│   ├── inference.py         # inference backend abstraction (Ollama / Anthropic)
│   ├── processor.py         # processing agent
│   ├── relevance.py         # Reddit relevance funnel (wire pre-rank, triage gate, feedback)
│   ├── writer.py            # Obsidian note writer
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── rss.py
│   │   ├── reddit.py        # public RSS feeds (top/.rss)
│   │   └── beatport.py
│   └── tests/
│       ├── __init__.py
│       ├── test_inference.py
│       ├── test_processor_lenses.py
│       ├── test_processor_routing.py
│       ├── test_reddit_adapter.py
│       └── test_relevance.py
└── configs/
    └── dyson-hope.yaml      # example instance config
```

---

## 7. Key Decisions + Rationale

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Beatport access | Web scrape (requests + BeautifulSoup) | No public API; HTML chart pages are stable and structured |
| Reddit access | **None — source dark** (`enabled: false`) | Live verification (2026-06-27) closed all three paths: unauthenticated `.json` → 403 edge-block (every UA/host/IP); OAuth → API-app creation gated by Reddit's Responsible Builder Policy (account-age/karma minimums + weeks-long manual pre-approval, commonly denied); public RSS → returns data but rate-limited to ~2 subs before sustained 429s. No dependable path, so Reddit is left dark. The adapter (RSS impl) and the relevance funnel are retained dormant and tested, ready to re-light if access opens. Decision record: JasonOS governance INI-100. |
| Reddit relevance | Precision funnel: wire pre-rank → lens-anchored LLM triage gate → comment deep-dive, with a vault-status feedback loop | Upvotes signal popularity, not reaction-worthiness; the funnel spends inference and calls only on posts likely worth a creative reaction, and sharpens from the operator's reacted/ignored marks |
| Vault write method | Direct file write (pathlib) | Obsidian vaults are local folders; no API needed |
| Inference routing | Ollama local-first (`llama3.1:8b`); Anthropic `claude-haiku-4-5-20251001` fallback | Reduces API cost and latency when a local server is available; fails open so a stopped Ollama never breaks a run |
| Scheduling | launchd plist | Native macOS; no external scheduler dependency |
| Social sources | Deferred | No viable API access path for Instagram/TikTok |

---

*End of design spec.*
