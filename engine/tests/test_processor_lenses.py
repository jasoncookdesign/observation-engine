"""INI-076-R1 hardening — the engine must tolerate lens entries returned as
name-bearing objects (e.g. llama3.1:8b emits [{"name": "..."}]) instead of
crashing _match_lenses on `.lower()`. Regression for the 2026-06-23 finding."""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
import processor  # noqa: E402


class TestNormalizeLensName(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(processor._normalize_lens_name("Historical Context"), "Historical Context")

    def test_name_bearing_dicts(self):
        self.assertEqual(processor._normalize_lens_name({"name": "Historical Context"}), "Historical Context")
        self.assertEqual(processor._normalize_lens_name({"lens": "Scene Economics"}), "Scene Economics")
        self.assertEqual(processor._normalize_lens_name({"title": "What's Changing"}), "What's Changing")

    def test_unusable_entries_return_none(self):
        self.assertIsNone(processor._normalize_lens_name({}))
        self.assertIsNone(processor._normalize_lens_name({"foo": "bar"}))
        self.assertIsNone(processor._normalize_lens_name(5))


class TestMatchLensesTolerant(unittest.TestCase):
    AVAIL = ["Historical Context", "Underground vs Mainstream"]

    def test_dict_form_lenses_resolve(self):
        out = processor._match_lenses(
            [{"name": "Historical Context"}, {"name": "Underground vs Mainstream"}], self.AVAIL)
        self.assertEqual(out, ["Historical Context", "Underground vs Mainstream"])

    def test_mixed_str_and_dict(self):
        out = processor._match_lenses(["historical context", {"name": "Underground vs Mainstream"}], self.AVAIL)
        self.assertEqual(out, ["Historical Context", "Underground vs Mainstream"])

    def test_malformed_skipped_then_fallback(self):
        out = processor._match_lenses([{"no_name": 1}, 7], self.AVAIL)
        self.assertEqual(out, [self.AVAIL[0]])  # safety fallback, no crash


LENS = "---\nname: scene-economics\n---\nHow money moves through a scene.\n"
DICT_LENS_JSON = (
    '{"observation": "x", "tags": ["a"], "interest_level": 4,'
    ' "lenses": [{"name": "scene-economics"}],'
    ' "questions": {"scene-economics": ["who profits?"]},'
    ' "expanded_context": "c"}'
)


class TestProcessConsumesDictLenses(unittest.TestCase):
    def test_end_to_end_dict_lenses(self):
        with tempfile.TemporaryDirectory() as d:
            lens_dir = Path(d) / "lenses"; lens_dir.mkdir()
            (lens_dir / "scene-economics.md").write_text(LENS)
            cfg = {"instance": {"purpose_context": "music"}, "output": {"vault_path": d}}
            raw = {"source": "rss", "source_url": "https://x/y", "title": "t",
                   "body": "b", "published_date": "2026-06-23", "raw_tags": []}
            with mock.patch.object(processor.inference, "generate_json",
                                   return_value=(DICT_LENS_JSON, "ollama")):
                out = processor.process(raw, cfg)
        self.assertIsNotNone(out)                       # would have crashed before
        self.assertEqual(out["lenses"], ["scene-economics"])
        self.assertIn("scene-economics", out["questions"])


if __name__ == "__main__":
    unittest.main()
