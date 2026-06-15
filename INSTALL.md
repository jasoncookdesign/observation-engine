# INI-057 — Music Culture Observation Engine: Install Guide

## 1. Install Python dependencies

```bash
pip3 install feedparser anthropic pyyaml requests beautifulsoup4
```

Run this once on the Mac mini. If `pip3` is not found, try `python3 -m pip install ...`.

---

## 2. Set the Anthropic API key in the plist

Open `com.jasonos.observation-engine.dyson-hope.plist` and replace `__SET_BY_CEO__` with your real key:

```xml
<key>ANTHROPIC_API_KEY</key>
<string>&lt;your-anthropic-api-key&gt;</string>
```

The key value is never committed to the repo — edit the plist file directly on the Mac mini after copying it to `~/Library/LaunchAgents/`.

---

## 3. Load the launchd job

Copy the plist to the LaunchAgents directory and load it:

```bash
cp /Volumes/SandboxData/workspaces/engineering/INI-057/com.jasonos.observation-engine.dyson-hope.plist \
   ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist
```

To verify it is loaded:

```bash
launchctl list | grep observation-engine
```

To unload (stop scheduling without deleting):

```bash
launchctl unload ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist
```

The job runs daily at 08:00. It does NOT run at load time (`RunAtLoad` is false).

---

## 4. Dry-run to validate

Run the pipeline in dry-run mode — fetches and processes observations but does not write to the vault:

```bash
cd /Volumes/SandboxData/workspaces/engineering/INI-057
python3 engine/main.py --config configs/dyson-hope.yaml --dry-run
```

Review stdout for fetch counts, processing output, and any errors before the first live run.

---

## 5. Manual one-off run

To trigger the full pipeline immediately (writes to vault):

```bash
ANTHROPIC_API_KEY=&lt;your-anthropic-api-key&gt; \
  python3 /Volumes/SandboxData/workspaces/engineering/INI-057/engine/main.py \
  --config /Volumes/SandboxData/workspaces/engineering/INI-057/configs/dyson-hope.yaml
```

Logs are written to:
- `stdout`: `/Volumes/SandboxData/Logs/observation-engine-dyson-hope.log`
- `stderr`: `/Volumes/SandboxData/Logs/observation-engine-dyson-hope-error.log`

---

## 6. Open the vault in Obsidian

1. In Obsidian, choose **Open folder as vault**.
2. Navigate to `/Volumes/SandboxData/observation-vaults/dyson-hope/` and open it.
3. Go to **Settings → Community plugins** and enable the **Dataview** plugin.

**Note: The Dataview plugin must be enabled for the Observation Inbox and Reaction Queue views to render.** Without it, the view notes display as raw Dataview query blocks rather than live tables.

---

## 7. Tune the config

Review subreddit selections in `configs/dyson-hope.yaml`. Current defaults:

```yaml
r/electronicmusic, r/DJs, r/techno, r/housemusic, r/aves, r/edmproduction, r/synthesizers
```

Add, remove, or reweight sources based on signal quality observed in the first week of output.
