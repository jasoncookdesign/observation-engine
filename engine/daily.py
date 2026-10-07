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
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

KEY_NAME = "ANTHROPIC_API_KEY"
DEFAULT_STATE = Path.home() / "Library" / "Logs" / "observation-engine"
DEFAULT_SECRETS = Path.home() / ".config" / "observation-engine" / "secrets"


def engine_main(argv: list[str]):
    """Run the engine's own CLI with argv (it reads sys.argv and may sys.exit); returns its counts."""
    import main as engine
    saved = sys.argv
    sys.argv = ["main.py", *argv]
    try:
        return engine.main()
    finally:
        sys.argv = saved


def _verdict(counts) -> str | None:
    """A failure message when the run did nothing useful because something broke, else None."""
    if not isinstance(counts, dict):
        return None
    if counts.get("processed", 0) == 0 and counts.get("failed", 0) > 0:
        return f"{counts['failed']} item(s) failed to process and none succeeded (is Ollama running, or the API key set?)"
    if counts.get("fetched", 0) == 0 and counts.get("adapter_errors", 0) > 0:
        return f"no source could be fetched ({counts['adapter_errors']} adapter error(s))"
    return None


@contextlib.contextmanager
def _capture_logs(stream):
    """Send all logging to `stream` for the run, whatever handlers the engine set up at import."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"))
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    try:
        yield
    finally:
        root.handlers, root.level = saved, level


class _RunFailed(Exception):
    pass


def _with_output(captured: io.StringIO, status: str) -> str:
    body = captured.getvalue().rstrip()
    return f"{body}\n{status}" if body else status


def _redact(text: str, key: str | None) -> str:
    return text.replace(key, "***") if key else text


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
    captured = io.StringIO()
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
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured), _capture_logs(captured):
            try:
                counts = engine_main(["--config", args.config])
            except SystemExit as stop:
                if stop.code not in (0, None):
                    raise
                counts = None
        problem = _verdict(counts)
        if problem:
            raise _RunFailed(problem)
        _log(args.state, now, _redact(_with_output(captured, "status=ok"), key))
        _write_marker(args.state, "success", f"{today} {now.isoformat()}")
        return 0
    except BaseException as exc:  # noqa: BLE001 - the one-line failure contract covers everything
        if isinstance(exc, KeyboardInterrupt):
            raise
        if isinstance(exc, _RunFailed):
            message = str(exc)
        elif isinstance(exc, SystemExit):
            errors = [l for l in captured.getvalue().splitlines() if "ERROR" in l or "error" in l]
            cause = errors[-1].split(" — ", 1)[-1] if errors else ""
            message = f"engine exited {exc.code}" + (f": {cause}" if cause else "")
        else:
            message = f"{type(exc).__name__}: {exc}"
        message = " ".join(message.split())
        if key:
            message = message.replace(key, "***")
        with contextlib.suppress(Exception):
            _log(args.state, now, _redact(_with_output(captured, f"status=failed {message}"), key))
            _write_marker(args.state, "failure", f"{now.isoformat()} {message}")
        print(f"observation-engine: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(run())
