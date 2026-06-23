"""Integration test: process() routes through inference
and builds the vault-ready dict from local-or-API JSON identically."""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
import processor  # noqa: E402

LENS = """---
name: scene-economics
---
How money moves through a music scene shapes who gets heard.
"""

CONTRACT_JSON = (
    '{"observation": "berghain adds resident dj series",'
    ' "tags": ["berlin","techno","berghain"],'
    ' "interest_level": 7,'
    ' "lenses": ["scene-economics"],'
    ' "questions": {"scene-economics": ["who profits?","who is gatekept?"]},'
    ' "expanded_context": "A monthly night for emerging selectors."}'
)


class TestProcessRouting(unittest.TestCase):
    def test_process_builds_dict_from_routed_json(self):
        with tempfile.TemporaryDirectory() as d:
            lens_dir = Path(d) / "lenses"
            lens_dir.mkdir()
            (lens_dir / "scene-economics.md").write_text(LENS)
            cfg = {
                "instance": {"purpose_context": "music culture"},
                "output": {"vault_path": d},
            }
            raw = {
                "source": "rss", "source_url": "https://x/y", "title": "t",
                "body": "b", "published_date": "2026-06-17", "raw_tags": [],
            }
            with mock.patch.object(
                processor.inference, "generate_json",
                return_value=(CONTRACT_JSON, "ollama"),
            ) as gj:
                out = processor.process(raw, cfg)
        gj.assert_called_once()
        self.assertIsNotNone(out)
        self.assertEqual(out["interest_level"], 5)  # clamped from 7
        self.assertEqual(out["lenses"], ["scene-economics"])
        self.assertIn("scene-economics", out["questions"])
        self.assertEqual(out["source_url"], "https://x/y")

    def test_process_returns_none_on_inference_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "lenses").mkdir()
            cfg = {"instance": {}, "output": {"vault_path": d}}
            with mock.patch.object(
                processor.inference, "generate_json",
                side_effect=RuntimeError("no backend"),
            ):
                out = processor.process({"source_url": "u"}, cfg)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
