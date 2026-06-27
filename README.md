# Observation Engine

A config-driven cultural observation engine. Fetches signals from RSS feeds, processes them with Claude, and writes structured notes to an Obsidian vault.

Built for [JasonOS](https://github.com/jasoncookdesign) to automate noticing — surface relevant signals daily so creative energy goes to interpretation, not monitoring.

---

## How it works

1. **Adapters** fetch raw items from configured sources. The RSS adapter is active. The Reddit and Beatport adapters are implemented but disabled: Reddit has no viable access path (unauthenticated `.json` is 403-blocked, OAuth app creation is gated by Reddit's Responsible Builder Policy, and public RSS is rate-limited to unusability), and Beatport is Cloudflare-blocked. The Reddit relevance funnel is retained, dormant and tested, ready to re-light if access ever opens.
2. **Relevance funnel** (Reddit) — before processing, Reddit items pass a precision-first funnel: a free wire-metric pre-rank, a lens-anchored LLM triage gate (reaction-worthiness, not popularity), and a comment deep-dive on survivors. A feedback loop harvests the vault's reacted/ignored status chain as few-shot exemplars so the gate sharpens over time. Other sources skip the funnel.
3. **Processor** routes each item through the inference backend (local Ollama model when available, Anthropic API as fallback) to produce a one-sentence observation summary, topic tags, an interest level (1–5), selected interpretive lenses, lens-scoped questions, and expanded context.
4. **Writer** renders each processed observation as a Markdown note with YAML frontmatter and writes it to an Obsidian vault inbox folder.
5. **Deduplication** — the engine reads existing vault notes on each run and skips any `source_url` already present.

The engine is parameterized via instance config — deploying for a new subject requires a new `configs/{name}.yaml`, not a fork.

---

## Project structure

```
engine/
  main.py           # Entry point and orchestration loop
  config.py         # Config loader and validator
  inference.py      # Inference backend abstraction (Ollama-first, Anthropic fallback)
  processor.py      # Observation processing agent
  relevance.py      # Reddit relevance funnel (wire pre-rank, triage gate, feedback)
  writer.py         # Obsidian vault note writer
  adapters/
    rss.py          # RSS/Atom feed adapter (active)
    reddit.py       # Reddit adapter (disabled/dark — no viable access path)
    beatport.py     # Beatport adapter (disabled — Cloudflare 403)
  tests/            # Unit and integration tests (stdlib unittest)
configs/
  dyson-hope.yaml   # Example instance config
```

---

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

Or individually:

```bash
pip3 install feedparser anthropic pyyaml requests beautifulsoup4 "ollama>=0.6.2,<0.7"
```

The `ollama` package is required for local inference. The Reddit adapter is disabled (no viable access path) and pulls in no Reddit-specific dependency.

### 2. Create an instance config

Copy `configs/dyson-hope.yaml` as a starting point. The config defines:

- `instance.name` and `instance.purpose_context` — who this is for and what signals are relevant
- `sources` — which adapters to enable and their parameters (feed URLs, subreddits, etc.)
- `output.vault_path` and `output.inbox_folder` — where to write notes
- `lens_library_path` — path to the Obsidian vault's lens library (relative to vault root)

### 3. Configure inference

The engine runs local-first: if an [Ollama](https://ollama.com) server is reachable at `http://localhost:11434` with the `llama3.1:8b` model resident, it is used. Otherwise the engine falls back to the Anthropic API. Ollama availability is tested on every run; a stopped server never breaks a run.

Environment variables (all optional — defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for the Anthropic fallback; omit only if Ollama is always available |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server base URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Local model tag |
| `OBS_PREFER_LOCAL` | `1` | Set to `0` or `false` to force API-only mode |

Keys are never committed to the repo.

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
