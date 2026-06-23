#!/bin/zsh
# =============================================================================
# JasonOS Observation Engine (Dyson Hope) — Activation Script
# =============================================================================
# Run this to install or reinstall the daily observation-engine launchd job:
#   - On first deployment (the plist must be BOOTSTRAPPED, not just copied)
#   - After a Mac restart that did not auto-load the agent
#   - After any plist loss from ~/Library/LaunchAgents/
#   - After editing the plist or run.sh
#
# This script is idempotent — safe to run multiple times.
#
# PREREQUISITE: /bin/zsh must have Full Disk Access.
#   System Settings -> Privacy & Security -> Full Disk Access -> + -> /bin/zsh
#
# What this does:
#   1. Preflight: SandboxData mounted, plist + run.sh + secrets present, python OK
#   2. Deploys the plist from the repo to ~/Library/LaunchAgents/ (deployed copy)
#   3. Boots out any prior instance, bootstraps the new one
#   4. Verifies registration
#   5. Kickstarts one immediate run and tails the log so you can confirm output
#
# Source of truth for the plist and run.sh is this repo on SandboxData.
# ~/Library/LaunchAgents/com.jasonos.observation-engine.dyson-hope.plist is a
# deployed copy. Edit the repo source, then re-run this script to redeploy.
# =============================================================================

set -euo pipefail

REPO="/Volumes/SandboxData/code/observation-engine"
LABEL="com.jasonos.observation-engine.dyson-hope"
PLIST_SRC="${REPO}/${LABEL}.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
RUN_SH="${REPO}/run.sh"
SECRETS="/Volumes/SandboxData/.jasonos-secrets"
PY="/opt/homebrew/bin/python3"
OUT_LOG="/Volumes/SandboxData/Logs/observation-engine-dyson-hope.log"
ERR_LOG="/Volumes/SandboxData/Logs/observation-engine-dyson-hope-error.log"
UID_VAL=$(id -u)

echo ""
echo "============================================="
echo " JasonOS Observation Engine — Activation"
echo "============================================="
echo ""

# -- Preflight ----------------------------------------------------------------
echo "[ 1/5 ] Preflight checks..."

if [ ! -f "$PLIST_SRC" ]; then
  echo "  x Plist source not found: $PLIST_SRC (is SandboxData mounted?)"
  exit 1
fi
echo "  ok Plist source: $PLIST_SRC"

if [ ! -f "$RUN_SH" ]; then
  echo "  x Launcher not found: $RUN_SH"
  exit 1
fi
echo "  ok Launcher: $RUN_SH"

if [ ! -f "$SECRETS" ]; then
  echo "  x Secrets file not found: $SECRETS"
  echo "    run.sh loads ANTHROPIC_API_KEY (fallback) and any keys from here."
  exit 1
fi
echo "  ok Secrets file present: $SECRETS"

if [ ! -x "$PY" ]; then
  echo "  x Python interpreter not found/executable: $PY"
  exit 1
fi
echo "  ok Python: $PY"

# -- Deploy plist -------------------------------------------------------------
echo "[ 2/5 ] Deploying plist..."
mkdir -p "${HOME}/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"
chmod 644 "$PLIST_DEST"
echo "  ok Deployed: $PLIST_DEST"

# -- Bootstrap LaunchAgent ----------------------------------------------------
echo "[ 3/5 ] Bootstrapping LaunchAgent..."

launchctl bootout "gui/${UID_VAL}" "$PLIST_DEST" 2>/dev/null && \
  echo "  .. booted out previous instance" || true

if launchctl bootstrap "gui/${UID_VAL}" "$PLIST_DEST"; then
  echo "  ok Bootstrapped: $LABEL"
else
  echo "  x launchctl bootstrap failed"
  echo "    Ensure /bin/zsh has Full Disk Access, then re-run."
  exit 1
fi

# -- Verify registration ------------------------------------------------------
echo "[ 4/5 ] Verifying registration..."
sleep 1
if launchctl list | grep -q "$LABEL"; then
  echo "  ok $LABEL is registered (will fire daily at 08:00)"
else
  echo "  x Agent not found in launchctl list after bootstrap"
  exit 1
fi

# -- Immediate verification run -----------------------------------------------
echo "[ 5/5 ] Kickstarting one immediate run to confirm output..."
launchctl kickstart "gui/${UID_VAL}/${LABEL}"
echo "  .. waiting up to 90s for the run to write logs..."
for i in {1..18}; do
  sleep 5
  if [ -f "$OUT_LOG" ]; then break; fi
done

echo ""
echo "---- stderr (last 20 lines) ----"
[ -f "$ERR_LOG" ] && tail -20 "$ERR_LOG" || echo "(no stderr log yet)"
echo "---- stdout (last 25 lines) ----"
[ -f "$OUT_LOG" ] && tail -25 "$OUT_LOG" || echo "(no stdout log yet — check again in a minute)"

echo ""
echo "============================================="
echo " Observation Engine is ACTIVE."
echo "============================================="
echo ""
echo " Schedule:       daily at 08:00 (StartCalendarInterval)"
echo " Plist source:   $PLIST_SRC   <- edit here, then re-run this script"
echo " Plist deployed: $PLIST_DEST"
echo " Vault output:   /Volumes/SandboxData/observation-vaults/dyson-hope-music-culture/Observation Inbox"
echo " stdout log:     $OUT_LOG"
echo " stderr log:     $ERR_LOG"
echo ""
echo " Manual immediate run:"
echo "   launchctl kickstart gui/${UID_VAL}/${LABEL}"
echo ""
echo " Stop scheduling (without deleting):"
echo "   launchctl bootout gui/${UID_VAL} $PLIST_DEST"
echo ""
echo " Re-run this activation after a restart or plist edit:"
echo "   zsh $REPO/jasonos-observation-engine-activate.command"
echo "============================================="
echo ""
echo " Press any key to close..."
read -r -k 1
