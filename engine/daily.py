"""Once-per-local-day launcher for the observation engine (launchd entry point).

launchd runs this hourly and at load (under job-alerts). It runs the engine at most once per
local calendar day, so a day the Mac slept through runs at the next awake tick, and the
engine's below-threshold items aren't re-scored every hour.

  python3 engine/daily.py --config configs/dyson-hope.yaml
      [--state ~/Library/Logs/observation-engine] [--secrets ~/.config/observation-engine/secrets]

Only ANTHROPIC_API_KEY is loaded from the secrets file (KEY=value lines). Without the file the
engine runs local-only (Ollama). On failure: exit 1 and exactly one stderr line,
"observation-engine: <message>", with the key redacted. Success and failure are recorded under
the state directory (success.txt holds the local date of the last good run).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
from datetime import datetime
from pathlib import Path

KEY_NAME = "ANTHROPIC_API_KEY"
DEFAULT_STATE = Path.home() / "Library" / "Logs" / "observation-engine"
DEFAULT_SECRETS = Path.home() / ".config" / "observation-engine" / "secrets"


def engine_main(argv: list[str]) -> None:
    """Run the engine's own CLI with argv (it reads sys.argv and may sys.exit)."""
    import main as engine
    saved = sys.argv
    sys.argv = ["main.py", *argv]
    try:
        engine.main()
    finally:
        sys.argv = saved


def _load_key(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == KEY_NAME and value.strip():
            return value.strip()
    return None


def _log(state: Path, now: datetime, text: str) -> None:
    with (state / "daily.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{now.isoformat()} {text}\n")


def _write_marker(state: Path, kind: str, text: str) -> None:
    tmp = state / f".{kind}.txt.tmp"
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, state / f"{kind}.txt")


def run(argv: list[str] | None = None, *, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the observation engine once per local day.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--secrets", type=Path, default=DEFAULT_SECRETS)
    args = parser.parse_args(argv)
    now = now or datetime.now().astimezone()
    today = now.date().isoformat()
    key = None
    try:
        args.state.mkdir(parents=True, exist_ok=True)
        success = args.state / "success.txt"
        if success.exists() and success.read_text(encoding="utf-8").split()[:1] == [today]:
            _log(args.state, now, "not due")
            return 0
        if args.secrets.exists():
            key = _load_key(args.secrets)
            if key:
                os.environ[KEY_NAME] = key
        else:
            _log(args.state, now, f"secrets file not found: {args.secrets}; running local-only")
        _write_marker(args.state, "attempt", now.isoformat())
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            engine_main(["--config", args.config])
        _log(args.state, now, captured.getvalue().rstrip() + "\nstatus=ok")
        _write_marker(args.state, "success", f"{today} {now.isoformat()}")
        return 0
    except BaseException as exc:  # noqa: BLE001 - the one-line failure contract covers everything
        if isinstance(exc, SystemExit) and exc.code in (0, None):
            _write_marker(args.state, "success", f"{today} {now.isoformat()}")
            return 0
        if isinstance(exc, KeyboardInterrupt):
            raise
        message = " ".join(f"{type(exc).__name__}: {exc}".split())
        if key:
            message = message.replace(key, "***")
        with contextlib.suppress(Exception):
            _log(args.state, now, f"status=failed {message}")
            _write_marker(args.state, "failure", f"{now.isoformat()} {message}")
        print(f"observation-engine: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(run())
