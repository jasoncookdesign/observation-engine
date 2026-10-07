#!/bin/zsh
# Unload and remove the observation-engine launchd agent.
# LAUNCH_AGENTS_DIR: where the plist was installed (default ~/Library/LaunchAgents).
set -euo pipefail

LABEL=com.jasoncookdesign.observation-engine
TARGET=${${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}:a}/$LABEL.plist

launchctl bootout gui/$UID/$LABEL 2>/dev/null || print "uninstall.sh: $LABEL was not loaded"
rm -f $TARGET
print "removed $TARGET"
