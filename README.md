# Observation Engine

A config-driven cultural observation engine. Fetches signals from RSS feeds and social sources, processes them with Claude, and writes structured notes to an Obsidian vault.

Built for [JasonOS](https://github.com/jasoncookdesign) to automate noticing — surface relevant signals daily so creative energy goes to interpretation, not monitoring.

---

## How it works

1. **Adapters** fetch raw items from configured sources (RSS feeds, Reddit, Beatport).
2. **Processor** sends each item to Claude Haiku, which produces a one-sentence observation summary, topic tags, an interest level (1–5), selected interpretive lenses, lens-scoped questions, and expanded context.
3. **Writer** renders each processed observation as a Markdown note with YAML frontmatter and writes it to an Obsidian vault inbox folder.
4. **Deduplication** — the engine reads existing vault notes on each run and skips any `source_url` already present.

The engine is parameterized via instance config — deploying for a new subject requires a new `configs/{name}.yaml`, not a fork.

---

## Project structure

```
engine/
  main.py           # Entry point and orchestration loop
  config.py         # Config loader and validator
  processor.py      # Claude API processing agent
  writer.py         # Obsidian vault note writer
  adapters/
    rss.py          # RSS/Atom feed adapter
    reddit.py       # Reddit RSS adapter
    beatport.py     # Beatport charts adapter
configs/
  dyson-hope.yaml   # Dyson Hope music culture instance
```

---

## Setup

### 1. Install dependencies

```bash
pip3 install feedparser anthropic pyyaml requests beautifulsoup4
```

### 2. Create an instance config

Copy `configs/dyson-hope.yaml` as a starting point. The config defines:

- `instance.name` and `instance.purpose_context` — who this is for and what signals are relevant
- `sources` — which adapters to enable and their parameters (feed URLs, subreddits, etc.)
- `output.vault_path` and `output.inbox_folder` — where to write notes
- `lens_library_path` — path to the Obsidian vault's lens library (relative to vault root)

### 3. Configure the API key

Set `ANTHROPIC_API_KEY` in your environment or in the launchd plist before running. The key is never committed to the repo.

### 4. Dry run

```bash
python3 engine/main.py --config configs/your-instance.yaml --dry-run
```

Fetches and processes observations but does not write to the vault. Review stdout before the first live run.

### 5. Run

```bash
ANTHROPIC_API_KEY=your-key \
  python3 engine/main.py --config configs/your-instance.yaml
```

---

## Scheduling (macOS launchd)

The repo includes a launchd plist template (`com.jasonos.observation-engine.dyson-hope.plist`) that runs the engine daily at 08:00. See `INSTALL.md` for full setup instructions.

---

## Obsidian vault structure

Each observation note is written with this frontmatter schema:

```yaml
id: 2026-06-15-ra-a3f1
date: 2026-06-15
source: "Resident Advisor"
source_url: "https://..."
observation: "One-sentence factual summary of the signal."
tags: [electronic-music, event-culture]
interest_level: 4
lenses: [Audience Positioning, Cultural Timing]
status: inbox
notes: ""
```

The body contains expanded context and lens-scoped interpretive questions. The vault is designed for use with the Obsidian **Dataview** plugin — inbox and queue views are Dataview queries.

---

## Lens library

Lenses are Obsidian notes in the vault's `lenses/` directory. Each lens has a `name` field in its YAML frontmatter and a prose description. The processor reads all available lenses at runtime and selects 1–3 per observation. Add or remove lenses by editing the vault — no code changes required.

---

## License

Private. All rights reserved.
