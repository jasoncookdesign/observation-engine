"""Tests for the once-per-local-day launcher (daily.py).
Run (from repo root): .venv/bin/python -m pytest -q engine/tests/test_daily.py
The engine itself is mocked; no network, model or vault is touched.
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
import daily  # noqa: E402

CHI = ZoneInfo("America/Chicago")
KEY = "sk-ant-api03-Zq9_x-TESTKEYvalue77"


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=CHI)


class DailyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "state"
        self.secrets = self.tmp / "secrets"
        self.secrets.write_text(f"# observation-engine\nANTHROPIC_API_KEY={KEY}\nOTHER_SECRET=nope\n")
        os.chmod(self.secrets, 0o600)
        self.config = self.tmp / "dyson-hope.yaml"
        self.config.write_text("instance: {}\n")
        self.env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self.env_patch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OTHER_SECRET", None)

    def tearDown(self):
        self.env_patch.stop()

    def run_daily(self, now, engine=None):
        argv = ["--config", str(self.config), "--state", str(self.state), "--secrets", str(self.secrets)]
        err = io.StringIO()
        engine = engine or mock.Mock(return_value=None)
        with mock.patch.object(daily, "engine_main", engine), redirect_stderr(err):
            rc = daily.run(argv, now=now)
        return rc, err.getvalue(), engine

    def test_runs_when_never_succeeded_and_records_local_date(self):
        rc, err, engine = self.run_daily(at("2026-10-07 10:00"))
        self.assertEqual((rc, err), (0, ""))
        engine.assert_called_once()
        self.assertEqual(engine.call_args.args[0], ["--config", str(self.config)])
        self.assertEqual((self.state / "success.txt").read_text().split()[0], "2026-10-07")

    def test_not_due_twice_on_the_same_local_day(self):
        self.run_daily(at("2026-10-07 08:00"))
        rc, err, engine = self.run_daily(at("2026-10-07 23:30"))
        self.assertEqual((rc, err), (0, ""))
        engine.assert_not_called()
        self.assertIn("not due", (self.state / "daily.log").read_text())

    def test_catch_up_runs_on_next_local_day(self):
        self.run_daily(at("2026-10-05 08:00"))
        rc, err, engine = self.run_daily(at("2026-10-07 14:00"))  # 10-06 missed (asleep)
        self.assertEqual(rc, 0)
        engine.assert_called_once()

    def test_local_day_not_utc_day(self):
        self.run_daily(at("2026-10-07 08:00"))
        # 20:00 CDT is 01:00Z on 10-08 but still 10-07 locally: not due.
        rc, err, engine = self.run_daily(at("2026-10-07 20:00"))
        engine.assert_not_called()

    def test_failure_is_one_redacted_line_and_stays_due(self):
        boom = mock.Mock(side_effect=RuntimeError(f"anthropic rejected key {KEY}"))
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=boom)
        lines = err.splitlines()
        self.assertEqual(rc, 1)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("observation-engine: "))
        self.assertNotIn(KEY, err)
        self.assertNotIn(KEY, (self.state / "daily.log").read_text())
        self.assertFalse((self.state / "success.txt").exists())
        self.assertTrue((self.state / "failure.txt").exists())
        rc2, _, engine2 = self.run_daily(at("2026-10-07 11:00"))
        engine2.assert_called_once()
        self.assertEqual(rc2, 0)

    def test_engine_system_exit_nonzero_is_a_failure(self):
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=mock.Mock(side_effect=SystemExit(1)))
        self.assertEqual(rc, 1)
        self.assertEqual(len(err.splitlines()), 1)

    def test_only_the_api_key_is_loaded_into_the_environment(self):
        seen = {}
        engine = mock.Mock(side_effect=lambda argv: seen.update(dict(os.environ)))
        self.run_daily(at("2026-10-07 10:00"), engine=engine)
        self.assertEqual(seen.get("ANTHROPIC_API_KEY"), KEY)
        self.assertNotIn("OTHER_SECRET", seen)

    def test_missing_secrets_file_runs_local_only(self):
        self.secrets.unlink()
        seen = {}
        engine = mock.Mock(side_effect=lambda argv: seen.update(dict(os.environ)))
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=engine)
        self.assertEqual((rc, err), (0, ""))
        self.assertNotIn("ANTHROPIC_API_KEY", seen)
        self.assertIn("secrets file not found", (self.state / "daily.log").read_text())

    # --- review conditions: meaningful success, failure causes kept ---
    def counts(self, **kw):
        base = {"fetched": 5, "processed": 5, "failed": 0, "written": 2, "adapter_errors": 0}
        base.update(kw)
        return mock.Mock(return_value=base)

    def test_every_item_failing_is_a_failure_and_stays_due(self):
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=self.counts(processed=0, failed=5, written=0))
        self.assertEqual(rc, 1)
        self.assertIn("5 item(s) failed to process", err)
        self.assertFalse((self.state / "success.txt").exists())

    def test_every_source_failing_with_nothing_fetched_is_a_failure(self):
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"),
                                    engine=self.counts(fetched=0, processed=0, written=0, adapter_errors=1))
        self.assertEqual(rc, 1)
        self.assertIn("no source could be fetched", err)

    def test_partial_failure_is_still_success(self):
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=self.counts(processed=3, failed=2))
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue((self.state / "success.txt").exists())

    def test_quiet_day_with_nothing_new_is_success(self):
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=self.counts(fetched=0, processed=0, written=0))
        self.assertEqual((rc, err), (0, ""))

    def test_system_exit_failure_keeps_the_cause(self):
        def config_error(argv):
            import logging
            logging.getLogger("observation-engine").error("Config error: output.vault_path is missing")
            raise SystemExit(1)
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=mock.Mock(side_effect=config_error))
        self.assertEqual(rc, 1)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertIn("Config error: output.vault_path is missing", err)
        self.assertIn("Config error: output.vault_path is missing", (self.state / "daily.log").read_text())

    def test_clean_system_exit_is_logged_as_ok(self):
        rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=mock.Mock(side_effect=SystemExit(0)))
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("status=ok", (self.state / "daily.log").read_text())

    def test_engine_logging_never_reaches_real_stderr(self):
        import logging
        stray = logging.StreamHandler(sys.__stderr__)  # as if `main` had been imported earlier
        logging.getLogger().addHandler(stray)
        try:
            def noisy(argv):
                logging.getLogger("observation-engine").warning("feed timed out")
                return {"fetched": 1, "processed": 1, "failed": 0, "written": 1, "adapter_errors": 0}
            with mock.patch.object(sys, "__stderr__", io.StringIO()) as real_err:
                stray.setStream(real_err)
                rc, err, _ = self.run_daily(at("2026-10-07 10:00"), engine=mock.Mock(side_effect=noisy))
            self.assertEqual((rc, err), (0, ""))
            self.assertEqual(real_err.getvalue(), "")
            self.assertIn("feed timed out", (self.state / "daily.log").read_text())
        finally:
            logging.getLogger().removeHandler(stray)


if __name__ == "__main__":
    unittest.main()
