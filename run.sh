#!/bin/zsh
# run.sh — Observation Engine launcher (canonical source)
# Loads secrets from /Volumes/SandboxData/.jasonos-secrets (not tracked in git)
# Installed by the activation script to ~/bin/jasonos-observation-engine.sh,
# which is what the launchd job execs (launchd cannot exec a script on the
# external /Volumes volume at spawn time — fails EX_CONFIG/78).

SECRETS="/Volumes/SandboxData/.jasonos-secrets"

if [ -f "$SECRETS" ]; then
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        export "$key=$value"
    done < "$SECRETS"
else
    echo "ERROR: Secrets file not found at $SECRETS" >&2
    exit 1
fi

exec /opt/homebrew/bin/python3 /Volumes/SandboxData/code/observation-engine/engine/main.py "$@"
