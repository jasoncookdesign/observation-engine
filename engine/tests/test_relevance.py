"""Unit tests for the INI-100 relevance funnel (engine/relevance.py).

Hermetic: Stage 1 (wire pre-rank) and Stage 5 (label harvest) are pure; Stage 2
(triage gate) runs against a fake generate_fn. No network, no real inference.
"""
import sys
import tempfile
import unittest
from pathlib import Path

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
import relevance  # noqa: E402


def _item(title, *, score=100, num_comments=10, upvote_ratio=0.9,
          is_self=True, is_video=False, domain="self.x", sub="x",
          permalink="/r/x/c/1/"):
    return {
        "title": title, "body": "b", "source_url": f"https://reddit.com{permalink}",
        "wire": {"subreddit": sub, "score": score, "num_comments": num_comments,
                 "upvote_ratio": upvote_ratio, "is_self": is_self,
                 "is_video": is_video, "domain": domain, "permalink": permalink},
    }


class WirePrerankTests(unittest.TestCase):
    def test_discussion_beats_eyecandy_at_equal_score(self):
        discussion = _item("debate", score=200, num_comments=180, is_self=True,
                           domain="self.x")
        eyecandy = _item("festival clip", score=200, num_comments=3,
                         is_self=False, is_video=True, domain="v.redd.it")
        ranked = relevance.wire_prerank([eyecandy, discussion])
        self.assertEqual(ranked[0]["title"], "debate")
        self.assertGreater(ranked[0]["wire_pre_score"], ranked[1]["wire_pre_score"])

    def test_taxonomy_title_match_boosts(self):
        plain = _item("new track out now", score=100, num_comments=10)
        onkw = _item("underground breakbeat scene shift", score=100, num_comments=10)
        ranked = relevance.wire_prerank([plain, onkw],
                                        taxonomy=["breakbeat", "underground", "scene"])
        self.assertEqual(ranked[0]["title"], "underground breakbeat scene shift")


class TriageGateTests(unittest.TestCase):
    def _gen_for(self, mapping, default=0):
        def gen(system, user):
            for key, score in mapping.items():
                if key in user:
                    return ('{"reaction_worthiness": %d, "best_lens": "x", "why": "w"}'
                            % score, "fake")
            return ('{"reaction_worthiness": %d}' % default, "fake")
        return gen

    def test_gate_splits_survivors_maybe_rejected(self):
        items = [_item("KEEP"), _item("MAYBE"), _item("DROP")]
        gen = self._gen_for({"KEEP": 5, "MAYBE": 2, "DROP": 0})
        survivors, maybe, rejected = relevance.triage_gate(
            items, "lenses", generate_fn=gen, threshold=3, maybe_band=1)
        self.assertEqual([i["title"] for i in survivors], ["KEEP"])
        self.assertEqual([i["title"] for i in maybe], ["MAYBE"])
        self.assertEqual([i["title"] for i in rejected], ["DROP"])

    def test_inference_error_routes_to_maybe(self):
        def boom(system, user):
            raise RuntimeError("model down")
        survivors, maybe, rejected = relevance.triage_gate(
            [_item("X")], "lenses", generate_fn=boom, threshold=3)
        self.assertEqual(survivors, [])
        self.assertEqual(len(maybe), 1)  # fail-open: not dropped

    def test_max_survivors_overflow_to_maybe(self):
        items = [_item(f"P{i}") for i in range(4)]
        gen = self._gen_for({}, default=5)  # all survive
        survivors, maybe, rejected = relevance.triage_gate(
            items, "lenses", generate_fn=gen, threshold=3, max_survivors=2)
        self.assertEqual(len(survivors), 2)
        self.assertEqual(len(maybe), 2)  # budget overflow kept as Maybe


class HarvestTests(unittest.TestCase):
    def _write(self, root, name, status, url):
        (root / name).write_text(
            f"---\ntitle: {name}\nstatus: {status}\nsource_url: {url}\n---\nbody\n",
            encoding="utf-8")

    def test_harvest_positives_and_hard_negatives(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "a.md", "reacted", "https://reddit.com/r/ableton/c/1/")
            self._write(root, "b.md", "archived", "https://reddit.com/r/aves/c/2/")
            self._write(root, "c.md", "inbox", "https://reddit.com/r/x/c/3/")
            labels = relevance.harvest_labels(str(root))
        self.assertEqual(len(labels["positives"]), 1)
        self.assertEqual(labels["positives"][0]["subreddit"], "ableton")
        self.assertEqual(len(labels["negatives"]), 1)  # archived = hard negative
        self.assertEqual(labels["negatives"][0]["subreddit"], "aves")

    def test_select_exemplars_caps(self):
        labels = {"positives": [{"title": f"p{i}"} for i in range(10)],
                  "negatives": [{"title": f"n{i}"} for i in range(10)]}
        ex = relevance.select_exemplars(labels, n_pos=3, n_neg=2)
        self.assertEqual(len(ex), 5)


class RunFunnelTests(unittest.TestCase):
    def test_end_to_end_with_deepdive(self):
        items = [_item("KEEP", permalink="/r/x/c/keep/"),
                 _item("DROP", permalink="/r/x/c/drop/")]

        def gen(system, user):
            score = 5 if "KEEP" in user else 0
            return ('{"reaction_worthiness": %d}' % score, "fake")

        calls = []
        def deep(permalink):
            calls.append(permalink)
            return ["a comment"]

        out = relevance.run_funnel(items, lens_summary="lenses", generate_fn=gen,
                                   threshold=3, deep_dive_fn=deep)
        self.assertEqual([i["title"] for i in out["survivors"]], ["KEEP"])
        self.assertEqual(calls, ["/r/x/c/keep/"])  # only survivor deep-dived
        self.assertIn("Top comments", out["survivors"][0]["body"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
