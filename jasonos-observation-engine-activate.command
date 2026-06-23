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
# IMPORTANT — why the launcher lives in ~/bin and logs in ~/Library/Logs:
#   launchd cannot exec a job's entry script, nor open its StandardOut/Err
#   paths, on the external /Volumes/SandboxData volume at spawn time — it fails
#   with EX_CONFIG (78) and produces no output. So the launcher is installed to
#   ~/bin (internal disk, matching every other JasonOS launchd job) and the
#   logs are written to ~/Library/Logs. The *running* engine still reads the
#   config and writes the vault on /Volumes/SandboxData normally.
#
# PREREQUISITE: /bin/zsh must have Full Disk Access.
#   System Settings -> Privacy & Security -> Full Disk Access -> + -> /bin/zsh
#
# What this does:
#   1. Preflight: SandboxData mounted, plist + run.sh + secrets present, python OK
#   2. Installs the launcher to ~/bin/jasonos-observation-engine.sh
#   3. Ensures ~/Library/Logs exists; deploys the plist to ~/Library/LaunchAgents/
#   4. Boots out any prior instance, bootstraps the new one, verifies
#   5. Kickstarts one immediate run and tails the log so you can confirm output
# =============================================================================

set -euo pipefail

REPO="/Volumes/SandboxData/code/observation-engine"
LABEL="com.jasonos.observation-engine.dyson-hope"
PLIST_SRC="${REPO}/${LABEL}.plist"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LAUNCHER_SRC="${REPO}/run.sh"
LAUNCHER_DEST="${HOME}/bin/jasonos-observation-engine.sh"
SECRETS="/Volumes/SandboxData/.jasonos-secrets"
PY="/opt/homebrew/bin/python3"
OUT_LOG="${HOME}/Library/Logs/observation-engine-dyson-hope.log"
ERR_LOG="${HOME}/Library/Logs/observation-engine-dyson-hope-error.log"
UID_VAL=$(id -u)

echo ""
echo "============================================="
echo " JasonOS Observation Engine — Activation"
echo "============================================="
echo ""

# -- Preflight ----------------------------------------------------------------
echo "[ 1/5 ] Preflight checks..."
[ -f "$PLIST_SRC" ]   || { echo "  x Plist source missing: $PLIST_SRC (SandboxData mounted?)"; exit 1; }
[ -f "$LAUNCHER_SRC" ]|| { echo "  x Launcher source missing: $LAUNCHER_SRC"; exit 1; }
[ -f "$SECRETS" ]     || { echo "  x Secrets file missing: $SECRETS"; exit 1; }
[ -x "$PY" ]          || { echo "  x Python not found/executable: $PY"; exit 1; }
echo "  ok plist, launcher, secrets, python all present"

# -- Install launcher to ~/bin (internal disk) --------------------------------
echo "[ 2/5 ] Installing launcher to ~/bin..."
mkdir -p "${HOME}/bin"
cp "$LAUNCHER_SRC" "$LAUNCHER_DEST"
chmod 755 "$LAUNCHER_DEST"
echo "  ok $LAUNCHER_DEST"

# -- Deploy plist + ensure log dir --------------------------------------------
echo "[ 3/5 ] Deploying plist and log directory..."
mkdir -p "${HOME}/Library/LaunchAgents" "${HOME}/Library/Logs"
cp "$PLIST_SRC" "$PLIST_DEST"
chmod 644 "$PLIST_DEST"
echo "  ok $PLIST_DEST"

# -- Bootstrap LaunchAgent ----------------------------------------------------
echo "[ 4/5 ] Bootstrapping LaunchAgent..."
launchctl bootout "gui/${UID_VAL}" "$PLIST_DEST" 2>/dev/null && echo "  .. booted out previous instance" || true
sleep 2
if launchctl bootstrap "gui/${UID_VAL}" "$PLIST_DEST"; then
  echo "  ok bootstrapped: $LABEL"
else
  echo "  x launchctl bootstrap failed (ensure /bin/zsh has Full Disk Access, then re-run)"
  exit 1
fi
launchctl list | grep -q "$LABEL" && echo "  ok registered (fires daily at 08:00)" || { echo "  x not registered"; exit 1; }

# -- Immediate verification run -----------------------------------------------
echo "[ 5/5 ] Kickstarting one immediate run..."
launchctl kickstart "gui/${UID_VAL}/${LABEL}"
sleep 8
echo ""
echo "---- ${ERR_LOG} (engine log, last 15 lines) ----"
[ -f "$ERR_LOG" ] && tail -15 "$ERR_LOG" || echo "(no log yet — check again shortly)"

echo ""
echo "============================================="
echo " Observation Engine is ACTIVE — daily at 08:00"
echo "============================================="
echo " Launcher:  $LAUNCHER_DEST   (copied from ${LAUNCHER_SRC})"
echo " Plist:     $PLIST_DEST"
echo " Logs:      $OUT_LOG"
echo "            $ERR_LOG"
echo " Vault:     /Volumes/SandboxData/observation-vaults/dyson-hope-music-culture/Observation Inbox"
echo ""
echo " Manual run:  launchctl kickstart gui/${UID_VAL}/${LABEL}"
echo " Stop:        launchctl bootout gui/${UID_VAL} $PLIST_DEST"
echo "============================================="
echo ""
echo " Press any key to close..."
read -r -k 1
