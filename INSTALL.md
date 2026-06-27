# Music Culture Observation Engine: Install Guide

The engine runs as a per-user launchd job and fires **daily at 08:00**.

> **One-step install / reinstall:** run the activation script from the repo
> root. It is idempotent and does everything below (install launcher to `~/bin`,
> deploy plist, bootstrap, verify, test-run):
>
> ```bash
> zsh /path/to/observation-engine/jasonos-observation-engine-activate.command
> ```
>
> Two things that are easy to get wrong and will silently break the daily run:
> 1. A plist sitting in `~/Library/LaunchAgents/` does **nothing** until it is
>    `launchctl bootstrap`-ed. Copying the file is not enough.
> 2. launchd cannot exec the entry script, nor open StandardOut/Err paths, on
>    an external volume — it fails with EX_CONFIG (78) and no output. So the
>    launcher lives in `~/bin` and logs go to `~/Library/Logs` (internal disk).
>    The running engine still reads config and writes the vault on the external
>    volume normally.

---

## 1. Install Python dependencies

Run once against the interpreter the job uses (`/opt/homebrew/bin/python3`):

```bash
/opt/homebrew/bin/python3 -m pip install -r /path/to/observation-engine/requirements.txt \
  --break-system-packages
```

---

## 2. Secrets (no keys in the plist)

The launcher (`run.sh`) reads a secrets file (`key=value` per line, not tracked
in git) and exports its contents as environment variables before exec-ing the
engine. Inference is local-first (Ollama) with Anthropic API as fallback, so
`ANTHROPIC_API_KEY` should be present in the secrets file to enable the fallback
path. The plist contains **no** API key.

Set the secrets file path by editing `run.sh` (`SECRETS=` at the top).

---

## 3. Load the launchd job (bootstrap — required)

The activation script in the box above is the supported path. The manual
equivalent (substitute `/path/to/observation-engine` for your actual repo path):

```bash
REPO=/path/to/observation-engine

cp "$REPO/run.sh" ~/bin/jasonos-observation-engine.sh
chmod 755 ~/bin/jasonos-observation-engine.sh
mkdir -p ~/Library/Logs
cp "$REPO/com.jasonos.observation-engine.dyson-hope.plist" ~/Library/LaunchAgents/

launchctl bootout   gui/$(id -u) ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist
launchctl list | grep observation-engine    # verify registered
```

Edit `run.sh` to point `SECRETS` at your secrets file and confirm the `exec` line
uses the correct Python interpreter and repo path before installing.

The job runs daily at 08:00. It does **not** run at load time (`RunAtLoad` is
false). Stop scheduling without deleting:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist
```

---

## 4. Dry-run to validate

Fetches and processes observations but does not write to the vault:

```bash
cd /path/to/observation-engine
/opt/homebrew/bin/python3 engine/main.py --config configs/dyson-hope.yaml --dry-run
```

---

## 5. Manual one-off run

Through launchd (same env, launcher, and secrets as the scheduled run):

```bash
launchctl kickstart gui/$(id -u)/com.jasonos.observation-engine.dyson-hope
```

Logs (internal disk):
- `stdout`: `~/Library/Logs/observation-engine-dyson-hope.log`
- `stderr`: `~/Library/Logs/observation-engine-dyson-hope-error.log` (engine logging)

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
