"""Unit tests for the INI-100 Reddit adapter (public RSS access mode).

Hermetic: a FakeSession returns canned Atom XML / status codes; no network.
Covers Atom parse + wire shape, top-N-per-sub (feed order), flair/category,
429 retry, HTML-challenge guard, fail-open, inter-sub spacing, and dedup.
"""
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
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self._responses:
            return self._responses.pop(0)
        return FakeResp(_feed([]))


def _entry(title, permalink, *, body="discussion body", flair="Discussion",
           ext_link="https://example.com"):
    # Reddit Atom content is escaped HTML with [link] + [comments] anchors.
    content = (f'&lt;div&gt;{body}&lt;/div&gt; '
               f'&lt;a href="{ext_link}"&gt;[link]&lt;/a&gt; '
               f'&lt;a href="{permalink}"&gt;[comments]&lt;/a&gt;')
    cat = f'<category term="{flair}"/>' if flair else ""
    return (f"<entry><title>{title}</title>"
            f'<link href="{permalink}"/>'
            f"<id>{permalink}</id>"
            f"<updated>2026-06-25T12:00:00+00:00</updated>"
            f"<author><name>/u/someone</name></author>"
            f'<content type="html">{content}</content>'
            f"{cat}</entry>")


def _feed(entries):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            + "".join(entries) + "</feed>")


class RssParseTests(unittest.TestCase):
    def test_parses_entry_into_wire_shape(self):
        feed = _feed([_entry("Sampling debate",
                             "https://www.reddit.com/r/ableton/comments/a1/x/")])
        sess = FakeSession([FakeResp(feed)])
        out = reddit.fetch({"subreddits": ["ableton"], "top_n_per_sub": 5},
                           session=sess, sleep=lambda s: None)
        self.assertEqual(len(out), 1)
        it = out[0]
        self.assertEqual(it["title"], "Sampling debate")
        self.assertEqual(it["source"], "Reddit/r/ableton")
        self.assertEqual(it["wire"]["subreddit"], "ableton")
        self.assertFalse(it["wire"]["metrics_available"])     # RSS has no metrics
        self.assertEqual(it["wire"]["domain"], "example.com")  # external link-out
        self.assertIn("ableton", it["raw_tags"])
        self.assertIn("discussion", it["raw_tags"])            # flair category
        self.assertIn("discussion body", it["body"])

    def test_top_n_keeps_feed_order(self):
        entries = [_entry(f"P{i}", f"https://www.reddit.com/r/x/comments/{i}/")
                   for i in range(5)]
        sess = FakeSession([FakeResp(_feed(entries))])
        out = reddit.fetch({"subreddits": ["x"], "top_n_per_sub": 2},
                           session=sess, sleep=lambda s: None)
        self.assertEqual([it["title"] for it in out], ["P0", "P1"])  # Reddit top-sort

    def test_429_retries_then_parses(self):
        feed = _feed([_entry("ok", "https://www.reddit.com/r/x/comments/a/")])
        sess = FakeSession([FakeResp("", 429), FakeResp(feed)])
        out = reddit.fetch({"subreddits": ["x"]}, session=sess, sleep=lambda s: None)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(sess.calls), 2)  # retried past the 429

    def test_html_challenge_fail_open(self):
        html = "<!DOCTYPE html><html><body class=theme-beta>blocked</body></html>"
        sess = FakeSession([FakeResp(html)] * 6)
        out = reddit.fetch({"subreddits": ["x"]}, session=sess, sleep=lambda s: None)
        self.assertEqual(out, [])  # zero items, no exception

    def test_403_gives_up_fail_open(self):
        sess = FakeSession([FakeResp("<html></html>", 403)])
        out = reddit.fetch({"subreddits": ["x"]}, session=sess, sleep=lambda s: None)
        self.assertEqual(out, [])

    def test_multi_sub_spacing_and_dedup(self):
        same = "https://www.reddit.com/r/shared/comments/z/"
        f1 = _feed([_entry("dup", same)])
        f2 = _feed([_entry("dup", same)])
        sess = FakeSession([FakeResp(f1), FakeResp(f2)])
        sleeps = []
        out = reddit.fetch({"subreddits": ["a", "b"], "request_delay_s": 3},
                           session=sess, sleep=lambda s: sleeps.append(s))
        self.assertEqual(len(out), 1)         # identical permalink deduped
        self.assertIn(3, sleeps)              # spacing delay applied between subs


class CommentsDisabledTests(unittest.TestCase):
    def test_fetch_comments_noop_in_rss_mode(self):
        # Stage-3 deep-dive is unavailable under RSS access (comment .json blocked).
        self.assertEqual(reddit.fetch_comments("/r/x/comments/a/"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
