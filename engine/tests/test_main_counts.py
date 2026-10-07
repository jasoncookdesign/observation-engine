"""main() returns its run counts so the launcher can tell a real outage from a quiet day."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
import main  # noqa: E402

REPO = _engine_dir.parent


def config_with_rss(tmp):
    cfg = yaml.safe_load((REPO / "configs" / "dyson-hope.yaml").read_text())
    for name, source in cfg["sources"].items():
        source["enabled"] = name == "rss"
    vault = tmp / "vault"
    (vault / "Observation Inbox").mkdir(parents=True)
    (vault / "lenses").mkdir()
    cfg["output"]["vault_path"] = str(vault)
    path = tmp / "c.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return path


def items(n):
    return [{"source": "Feed", "source_url": f"https://example.test/{i}", "title": f"t{i}",
             "date": "2026-10-07", "content": "x"} for i in range(n)]


class MainCounts(unittest.TestCase):
    def run_main(self, fetch, process):
        tmp = Path(tempfile.mkdtemp())
        adapter = mock.Mock(spec=["fetch"], fetch=fetch)  # a fetch-only adapter (no fetch_with_stats)
        with mock.patch.object(sys, "argv", ["main.py", "--config", str(config_with_rss(tmp))]), \
             mock.patch.object(main, "_load_adapter", return_value=adapter), \
             mock.patch.object(main.processor, "process", process):
            return main.main()

    def test_counts_when_every_item_fails(self):
        result = self.run_main(mock.Mock(return_value=items(3)), mock.Mock(return_value=None))
        self.assertEqual((result["fetched"], result["processed"], result["failed"]), (3, 0, 3))
        self.assertEqual(result["adapter_errors"], 0)

    def test_counts_adapter_error(self):
        result = self.run_main(mock.Mock(side_effect=RuntimeError("feed down")), mock.Mock())
        self.assertEqual((result["fetched"], result["adapter_errors"]), (0, 1))

    def test_counts_write_errors_separately(self):
        processed = {"source_url": "https://example.test/0", "interest_level": 5}
        with mock.patch.object(main.writer, "write", side_effect=OSError("read-only vault")):
            result = self.run_main(mock.Mock(return_value=items(2)), mock.Mock(return_value=processed))
        self.assertEqual((result["processed"], result["written"], result["write_errors"]), (2, 0, 2))

    def test_counts_feed_failures_when_adapter_reports_them(self):
        adapter = mock.Mock()
        adapter.fetch_with_stats = mock.Mock(return_value=([], 3, 3))
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(sys, "argv", ["main.py", "--config", str(config_with_rss(tmp))]), \
             mock.patch.object(main, "_load_adapter", return_value=adapter):
            result = main.main()
        self.assertEqual((result["feeds_attempted"], result["feeds_failed"]), (3, 3))


if __name__ == "__main__":
    unittest.main()
