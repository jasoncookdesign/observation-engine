# INI-057 — Music Culture Observation Engine: Install Guide

The engine runs as a per-user launchd job on the Mac mini and fires **daily at
08:00**. Repo lives at `/Volumes/SandboxData/code/observation-engine/`.

> **One-step install / reinstall:** run the activation script. It is idempotent
> and does everything below (deploy plist, bootstrap, verify, test-run):
>
> ```bash
> zsh /Volumes/SandboxData/code/observation-engine/jasonos-observation-engine-activate.command
> ```
>
> A plist sitting in `~/Library/LaunchAgents/` does **nothing** until it is
> bootstrapped into launchd. Copying the file is not enough — you must run the
> activation script (or `launchctl bootstrap`, below) at least once.

---

## 1. Install Python dependencies

Run once on the Mac mini, against the interpreter the job uses
(`/opt/homebrew/bin/python3`):

```bash
/opt/homebrew/bin/python3 -m pip install -r \
  /Volumes/SandboxData/code/observation-engine/requirements.txt --break-system-packages
```

---

## 2. Secrets (no keys in the plist)

The job loads secrets from `/Volumes/SandboxData/.jasonos-secrets` via `run.sh`
(`key=value` per line, not tracked in git). Inference is local-first (Ollama)
and falls back to the Anthropic API, so `ANTHROPIC_API_KEY` should be present
there for the fallback path. The plist contains **no** API key.

---

## 3. Load the launchd job (bootstrap — required)

The activation script in the box above is the supported path. The manual
equivalent, if needed:

```bash
cp /Volumes/SandboxData/code/observation-engine/com.jasonos.observation-engine.dyson-hope.plist \
   ~/Library/LaunchAgents/

launchctl bootout   gui/$(id -u) ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist
```

Verify it is registered:

```bash
launchctl list | grep observation-engine
```

Stop scheduling without deleting:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist
```

The job runs daily at 08:00. It does **not** run at load time (`RunAtLoad` is
false) — use `launchctl kickstart` (section 5) to run on demand.

---

## 4. Dry-run to validate

Fetches and processes observations but does not write to the vault:

```bash
cd /Volumes/SandboxData/code/observation-engine
/opt/homebrew/bin/python3 engine/main.py --config configs/dyson-hope.yaml --dry-run
```

---

## 5. Manual one-off run

Through launchd (uses the same env + secrets as the scheduled run):

```bash
launchctl kickstart gui/$(id -u)/com.jasonos.observation-engine.dyson-hope
```

Logs:
- `stdout`: `/Volumes/SandboxData/Logs/observation-engine-dyson-hope.log`
- `stderr`: `/Volumes/SandboxData/Logs/observation-engine-dyson-hope-error.log`

---

## 6. Open the vault in Obsidian

1. In Obsidian, choose **Open folder as vault**.
2. Open `/Volumes/SandboxData/observation-vaults/dyson-hope-music-culture/`.
3. **Settings → Community plugins** and enable **Dataview** (required for the
   Observation Inbox / Reaction Queue views to render).

---

## 7. Tune the config

Sources live in `configs/dyson-hope.yaml`. RSS is the only active adapter;
Reddit and Beatport are disabled. Add, remove, or reweight feeds based on signal
quality observed in the output.
