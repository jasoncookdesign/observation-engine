"""Production entry points: engine/daily.py as a subprocess, and the launchd plist render.
Run (from repo root): .venv/bin/python -m pytest -q engine/tests/test_launch.py
No network (dead proxy, every source disabled), no model, no launchctl (RENDER_ONLY / fake).
"""
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LABEL = "com.jasoncookdesign.observation-engine"


def offline_config(tmp: Path) -> Path:
    cfg = yaml.safe_load((REPO / "configs" / "dyson-hope.yaml").read_text())
    for source in cfg.get("sources", {}).values():
        if isinstance(source, dict):
            source["enabled"] = False
    vault = tmp / "vault"
    (vault / "Observation Inbox").mkdir(parents=True)
    (vault / "lenses").mkdir()
    cfg["output"]["vault_path"] = str(vault)
    path = tmp / "offline.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


class DailyEntryPoint(unittest.TestCase):
    def test_daily_runs_engine_records_success_then_not_due(self):
        tmp = Path(tempfile.mkdtemp())
        state = tmp / "state"
        env = {**os.environ, "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
               "OLLAMA_HOST": "http://127.0.0.1:9", "HOME": str(tmp)}
        cmd = [sys.executable, str(REPO / "engine" / "daily.py"), "--config", str(offline_config(tmp)),
               "--state", str(state), "--secrets", str(tmp / "no-secrets")]
        first = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, "")
        self.assertTrue((state / "success.txt").exists())
        second = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        self.assertIn("not due", (state / "daily.log").read_text())

    def test_every_feed_unreachable_is_a_failure_not_a_quiet_day(self):
        tmp = Path(tempfile.mkdtemp())
        cfg = yaml.safe_load(offline_config(tmp).read_text())
        cfg["sources"]["rss"]["enabled"] = True
        cfg["sources"]["rss"]["feeds"] = [{"name": "Dead A", "url": "http://127.0.0.1:9/a.xml", "slug": "a"},
                                          {"name": "Dead B", "url": "http://127.0.0.1:9/b.xml", "slug": "b"}]
        path = tmp / "dead-feeds.yaml"
        path.write_text(yaml.safe_dump(cfg))
        cmd = [sys.executable, str(REPO / "engine" / "daily.py"), "--config", str(path),
               "--state", str(tmp / "state"), "--secrets", str(tmp / "none")]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                           env={**os.environ, "HOME": str(tmp), "OLLAMA_HOST": "http://127.0.0.1:9"})
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1)
        self.assertIn("2 of 2 feeds failed", r.stderr)
        self.assertFalse((tmp / "state" / "success.txt").exists())

    def test_bad_config_is_one_line_failure(self):
        tmp = Path(tempfile.mkdtemp())
        cmd = [sys.executable, str(REPO / "engine" / "daily.py"), "--config", str(tmp / "missing.yaml"),
               "--state", str(tmp / "state"), "--secrets", str(tmp / "none")]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env={**os.environ, "HOME": str(tmp)})
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertTrue(r.stderr.startswith("observation-engine: "))


class LaunchdRender(unittest.TestCase):
    def render(self, tmp: Path, extra=None):
        alerts = tmp / "job-alerts"
        alerts.mkdir()
        (alerts / "job_alert.py").write_text("# stand-in\n")
        env = {**os.environ, "RENDER_ONLY": str(tmp / "agents"), "JOB_ALERTS": str(alerts),
               "ENGINE_PYTHON": sys.executable, "OBS_STATE": str(tmp / "Logs & state"), **(extra or {})}
        r = subprocess.run(["/bin/zsh", str(REPO / "launchd" / "install.sh")], env=env,
                           capture_output=True, text=True, timeout=60)
        return r, tmp / "agents" / f"{LABEL}.plist", alerts

    def test_plist_shape(self):
        tmp = Path(tempfile.mkdtemp())
        r, plist, alerts = self.render(tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(subprocess.run(["plutil", "-lint", "-s", str(plist)]).returncode, 0)
        data = plistlib.loads(plist.read_bytes())
        self.assertEqual(set(data), {"Label", "ProgramArguments", "WorkingDirectory", "EnvironmentVariables",
                                     "StandardOutPath", "StandardErrorPath", "StartInterval", "RunAtLoad"})
        self.assertEqual(data["Label"], LABEL)
        self.assertEqual((data["StartInterval"], data["RunAtLoad"]), (3600, True))
        args = data["ProgramArguments"]
        self.assertEqual(args[1:4], [str(alerts / "job_alert.py"), "--job", "observation-engine"])
        tail = args[args.index("--") + 1:]
        self.assertEqual(tail, [sys.executable, str(REPO / "engine" / "daily.py"), "--config",
                                str(REPO / "configs" / "dyson-hope.yaml"), "--state", str(tmp / "Logs & state")])
        logs = [args[i + 1] for i, a in enumerate(args) if a == "--log"]
        self.assertEqual(sorted(logs), sorted([data["StandardOutPath"], data["StandardErrorPath"]]))
        self.assertIn("/opt/homebrew/bin", data["EnvironmentVariables"]["PATH"].split(":"))
        for value in [*args, data["WorkingDirectory"], data["StandardOutPath"]]:
            self.assertNotIn("~", value)

    def test_missing_engine_python_installs_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        r, plist, _ = self.render(tmp, {"ENGINE_PYTHON": str(tmp / "no-venv" / "python")})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(plist.exists())


if __name__ == "__main__":
    unittest.main()
