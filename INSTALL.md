# Music Culture Observation Engine: Install Guide (Ono-Sendai)

The engine runs as a per-user launchd job, `com.jasoncookdesign.observation-engine`. launchd fires it **hourly and at load**, wrapped in [job-alerts](https://github.com/jasoncookdesign/job-alerts). Its entry point, `engine/daily.py`, runs the engine **at most once per local day**, so a day the Mac slept through catches up at the next awake tick, and below-threshold items aren't re-scored every hour. The vault is `~/Vaults/observation`, which is local and outside git (work#52).

---

## 1. Python environment (project-local)

```bash
cd ~/Sites/observation-engine
uv venv .venv --python /usr/local/bin/python3
uv pip install --python .venv/bin/python -r requirements.txt pytest
.venv/bin/python -m pytest -q engine/tests
```

---

## 2. Inference and secrets

- **Local first:** Ollama at `http://localhost:11434` with `llama3.1:8b` (`ollama pull llama3.1:8b`). The Ollama app starts at login. With a Homebrew install, run `brew services start ollama` instead.
- **Fallback:** the Anthropic API. Put the key in `~/.config/observation-engine/secrets` (mode 600) as one unquoted line, `ANTHROPIC_API_KEY=…`. `daily.py` loads only that key. Without the file the engine runs local-only.

---

## 3. Install the launchd job

```bash
zsh launchd/install.sh      # renders, lints with plutil, bootstraps; RunAtLoad runs it once now
zsh launchd/uninstall.sh    # unload and remove
```

Environment overrides:
- `ENGINE_PYTHON`: defaults to `.venv/bin/python`.
- `ALERT_PYTHON`: defaults to `/usr/local/bin/python3`.
- `JOB_ALERTS`: defaults to `~/Sites/job-alerts`.
- `OBS_STATE`: defaults to `~/Library/Logs/observation-engine`.
- `LAUNCH_AGENTS_DIR`: where the plist is installed.
- `RENDER_ONLY=<dir>`: renders the plist without loading it.

A failing run exits 1 with one `observation-engine: …` stderr line, which opens "Scheduled job failing: observation-engine" in the work queue.

---

## 4. Dry run to validate

Fetches and processes observations but doesn't write to the vault:

```bash
.venv/bin/python engine/main.py --config configs/dyson-hope.yaml --dry-run
```

---

## 5. Manual run

```bash
.venv/bin/python engine/daily.py --config configs/dyson-hope.yaml    # honors once-per-day
.venv/bin/python engine/main.py --config configs/dyson-hope.yaml     # runs now, unconditionally
launchctl kickstart gui/$(id -u)/com.jasoncookdesign.observation-engine
```

Logs and markers: `~/Library/Logs/observation-engine/`, holding `daily.log`, `success.txt` (the local date of the last good run), `failure.txt` and the launchd stdout and stderr logs.

---

## 6. Open the vault in Obsidian

1. In Obsidian, choose **Open folder as vault**.
2. Open the directory configured as `output.vault_path` in your instance config.
3. **Settings → Community plugins** and enable **Dataview** (required for the
   Observation Inbox / Reaction Queue views to render).

---

## 7. Tune the config

Sources live in `configs/dyson-hope.yaml`. RSS is active; Reddit and Beatport are
disabled. Reddit is **dark** — no viable access path (unauthenticated `.json` is
403-blocked, OAuth app creation is gated by Reddit's Responsible Builder Policy, and
public RSS rate-limits to unusability); the adapter and its relevance funnel are
retained dormant for if access ever opens. Add, remove, or reweight RSS feeds based
on signal quality observed in the output.
