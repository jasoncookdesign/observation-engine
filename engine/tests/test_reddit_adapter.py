"""Unit tests for the INI-100 unauthenticated .json Reddit adapter.

Hermetic: a FakeSession returns canned JSON/HTML; no network. Covers listing
parse + wire metrics, top-N-per-sub selection, min_score_floor, HTML-not-JSON
guard with retry, fail-open, and the comment deep-dive.
"""
import json
import sys
import unittest
from pathlib import Path

_engine_dir = Path(__file__).resolve().parent.parent
if str(_engine_dir) not in sys.path:
    sys.path.insert(0, str(_engine_dir))
from adapters import reddit  # noqa: E402


class FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


class FakeSession:
    """Returns queued responses per call; records requested URLs."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self._responses:
            return self._responses.pop(0)
        return FakeResp('{"data":{"children":[]}}')


def _listing(posts):
    return json.dumps({"data": {"children": [{"data": p} for p in posts]}})


def _post(**kw):
    base = {"title": "t", "selftext": "", "score": 100, "num_comments": 10,
            "upvote_ratio": 0.9, "permalink": "/r/x/comments/abc/t/",
            "url": "https://x", "created_utc": 1_700_000_000, "is_video": False,
            "is_self": True, "domain": "self.x", "link_flair_text": "Discussion"}
    base.update(kw)
    return base


class ParseTests(unittest.TestCase):
    def test_parses_wire_metrics(self):
        sess = FakeSession([FakeResp(_listing([_post(title="hello", score=250,
                                                     num_comments=80)]))])
        out = reddit.fetch({"subreddits": ["x"], "top_n_per_sub": 5},
                           session=sess, sleep=lambda s: None)
        self.assertEqual(len(out), 1)
        it = out[0]
        self.assertEqual(it["title"], "hello")
        self.assertEqual(it["source"], "Reddit/r/x")
        self.assertEqual(it["wire"]["score"], 250)
        self.assertEqual(it["wire"]["num_comments"], 80)
        self.assertIn("x", it["raw_tags"])
        self.assertIn("discussion", it["raw_tags"])  # flair lowercased/hyphenated

    def test_top_n_per_sub_and_floor(self):
        posts = [_post(title=f"p{i}", score=s, permalink=f"/r/x/comments/{i}/")
                 for i, s in enumerate([300, 200, 100, 4, 1])]  # last two below floor=5
        sess = FakeSession([FakeResp(_listing(posts))])
        out = reddit.fetch({"subreddits": ["x"], "top_n_per_sub": 2,
                            "min_score_floor": 5}, session=sess, sleep=lambda s: None)
        # floor removes the 4 and 1; top_n=2 keeps the two highest.
        self.assertEqual([it["wire"]["score"] for it in out], [300, 200])

    def test_html_challenge_retries_then_parses(self):
        html = "<!DOCTYPE html><html><head></head><body>blocked</body></html>"
        sess = FakeSession([FakeResp(html), FakeResp(_listing([_post()]))])
        out = reddit.fetch({"subreddits": ["x"]}, session=sess, sleep=lambda s: None)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(sess.calls), 2)  # retried past the HTML challenge

    def test_fail_open_on_persistent_html(self):
        html = "<!DOCTYPE html><html></html>"
        sess = FakeSession([FakeResp(html)] * 6)  # never recovers
        out = reddit.fetch({"subreddits": ["x"]}, session=sess, sleep=lambda s: None)
        self.assertEqual(out, [])  # zero items, no exception

    def test_multi_sub_dedup(self):
        same = _post(permalink="/r/shared/comments/z/")
        sess = FakeSession([FakeResp(_listing([same])), FakeResp(_listing([same]))])
        out = reddit.fetch({"subreddits": ["a", "b"]}, session=sess, sleep=lambda s: None)
        self.assertEqual(len(out), 1)  # identical permalink deduped across subs


class CommentTests(unittest.TestCase):
    def test_fetch_comments_extracts_bodies(self):
        comments = {"data": {"children": [
            {"data": {"body": "great take"}},
            {"data": {"body": "[deleted]"}},
            {"data": {"body": "disagree, here's why"}},
        ]}}
        payload = json.dumps([{"data": {}}, comments])
        sess = FakeSession([FakeResp(payload)])
        out = reddit.fetch_comments("/r/x/comments/abc/t/", session=sess,
                                    sleep=lambda s: None)
        self.assertEqual(out, ["great take", "disagree, here's why"])

    def test_fetch_comments_fail_open(self):
        sess = FakeSession([FakeResp("<!DOCTYPE html></html>")] * 6)
        self.assertEqual(reddit.fetch_comments("/r/x/c/", session=sess,
                                               sleep=lambda s: None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
