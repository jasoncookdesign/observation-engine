#!/bin/zsh
# run.sh — Observation Engine launcher
# Loads secrets from /Volumes/SandboxData/.jasonos-secrets (not tracked in git)
# Called by com.jasonos.observation-engine.dyson-hope launchd daemon

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
