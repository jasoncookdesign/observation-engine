#!/bin/zsh
# Install the observation engine as a launchd agent: hourly and at load, wrapped in job-alerts.
# engine/daily.py runs the engine at most once per local day, so missed days catch up on wake.
#
# Environment:
#   ALERT_PYTHON       interpreter for job_alert.py (default /usr/local/bin/python3)
#   ENGINE_PYTHON      interpreter with requirements.txt installed (default <repo>/.venv/bin/python)
#   JOB_ALERTS         checkout of jasoncookdesign/job-alerts (default ~/Sites/job-alerts)
#   OBS_STATE          logs and markers (default ~/Library/Logs/observation-engine)
#   LAUNCH_AGENTS_DIR  where the plist goes (default ~/Library/LaunchAgents)
#   RENDER_ONLY=<dir>  render the plist into <dir>; no launchctl
set -euo pipefail

LABEL=com.jasoncookdesign.observation-engine
REPO=${0:A:h:h}
TEMPLATE=$REPO/launchd/$LABEL.plist.template
ALERT_PYTHON=${ALERT_PYTHON:-/usr/local/bin/python3}
ENGINE_PYTHON=${ENGINE_PYTHON:-$REPO/.venv/bin/python}
JOB_ALERT=${${JOB_ALERTS:-$HOME/Sites/job-alerts}:a}/job_alert.py
STATE=${${OBS_STATE:-$HOME/Library/Logs/observation-engine}:a}

for need in $JOB_ALERT $ENGINE_PYTHON; do
  if [[ ! -e $need ]]; then
    print -u2 "install.sh: $need not found (see README: set JOB_ALERTS, or create .venv with requirements.txt)"
    exit 1
  fi
done

xml() {
  local s=$1
  s=${s//&/&amp;}; s=${s//</&lt;}; s=${s//>/&gt;}; s=${s//\"/&quot;}
  print -rn -- $s
}

plist=$(<$TEMPLATE)
plist=${plist//@ALERT_PYTHON@/$(xml ${ALERT_PYTHON:a})}
plist=${plist//@ENGINE_PYTHON@/$(xml ${ENGINE_PYTHON:a})}
plist=${plist//@JOB_ALERT@/$(xml $JOB_ALERT)}
plist=${plist//@STDOUT@/$(xml $STATE/launchd.out.log)}
plist=${plist//@STDERR@/$(xml $STATE/launchd.err.log)}
plist=${plist//@STATE@/$(xml $STATE)}
plist=${plist//@REPO@/$(xml $REPO)}

if [[ -n ${RENDER_ONLY:-} ]]; then
  TARGET_DIR=${RENDER_ONLY:a}
else
  TARGET_DIR=${${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}:a}
fi
TARGET=$TARGET_DIR/$LABEL.plist

RENDERED=$(mktemp "${TMPDIR:-/tmp}/$LABEL.XXXXXX")
trap 'rm -f $RENDERED' EXIT
print -r -- $plist > $RENDERED
chmod 644 $RENDERED
plutil -lint -s $RENDERED

mkdir -p $STATE $TARGET_DIR
mv -f $RENDERED $TARGET

if [[ -n ${RENDER_ONLY:-} ]]; then
  print "rendered $TARGET"
  exit 0
fi

launchctl bootout gui/$UID/$LABEL 2>/dev/null || true
if ! launchctl bootstrap gui/$UID $TARGET; then
  print -u2 "install.sh: launchctl bootstrap failed; retrying once"
  sleep 2
  launchctl bootstrap gui/$UID $TARGET
fi
print "installed $TARGET"
