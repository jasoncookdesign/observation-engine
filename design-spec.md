# INI-057 — Music Culture Observation Engine: Design Spec

**Status:** Phase 1 complete
**Author:** President Agent + Engineering Director
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
notes: ""                                              # Dyson Hope fills this in
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

The instance config is a YAML file that drives the engine for one deployment. Engine core reads this file at startup. No Dyson Hope-specific values appear in engine code.

```yaml
# dyson-hope.yaml — INI-057 instance config

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
    enabled: true
    subreddits:
      - electronicmusic
      - DJs
      - techno
      - housemusic
      - aves
      - edmproduction
      - synthesizers
    post_limit: 25
    min_score: 50          # minimum upvotes to include

  beatport:
    enabled: true
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
  vault_path: "/Volumes/SandboxData/observation-vaults/dyson-hope/"
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
└── README.md                        # vault orientation for Dyson Hope
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

The processing agent receives raw observations from adapters and transforms them into structured vault notes. All prompts are parameterized — no hardcoded references to Dyson Hope or music culture.

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

The lens library is summarized as a list of `name: one-line description` entries for prompt injection. Full lens notes live in the vault and are for Dyson Hope's reference, not the prompt.

---

## 6. Workspace Layout

```
/Volumes/SandboxData/workspaces/engineering/INI-057/
├── design-spec.md           # this document
├── engine/
│   ├── main.py              # CLI entry point + pipeline runner
│   ├── config.py            # config loader + validator
│   ├── processor.py         # processing agent (Claude API)
│   ├── writer.py            # Obsidian note writer
│   ├── scheduler.py         # launchd plist generator
│   └── adapters/
│       ├── __init__.py
│       ├── rss.py
│       ├── reddit.py
│       └── beatport.py
├── configs/
│   └── dyson-hope.yaml      # instance config
├── tests/
│   ├── test_adapters.py
│   └── test_processor.py
└── com.jasonos.observation-engine.dyson-hope.plist   # launchd schedule
```

---

## 7. Key Decisions + Rationale

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Beatport access | Web scrape (requests + BeautifulSoup) | No public API; HTML chart pages are stable and structured |
| Reddit access | PRAW (official Python Reddit API wrapper) | Clean, rate-limit-aware, no key scraping |
| Vault write method | Direct file write (pathlib) | Obsidian vaults are local folders; no API needed |
| Processing model | Claude claude-haiku-4-5 (cost) / fallback sonnet | High-volume daily processing; Haiku is sufficient for categorization |
| Scheduling | launchd plist | Native macOS; consistent with JasonOS infrastructure pattern |
| Social sources | Deferred | No viable API access path for Instagram/TikTok; deferred per INI-057 scope |

---

*End of design spec. Phase 2 begins vault creation. Phase 3 begins engine build.*
