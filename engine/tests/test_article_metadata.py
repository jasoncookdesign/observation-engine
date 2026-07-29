import unittest

from article_metadata import build
from writer import _render_note


class TestArticleMetadata(unittest.TestCase):
    def test_build_preserves_source_facts_and_normalizes_relevance(self):
        metadata = build(
            {
                "title": "Bandcamp changes discovery",
                "source": "Music Ally",
                "source_url": "https://example.test/article",
                "published_date": "2026-07-28",
                "raw_tags": ["bandcamp", "music-business"],
            },
            {
                "observation": "Bandcamp changes discovery.",
                "expanded_context": "The platform changes how listeners find releases.",
                "tags": ["bandcamp", "music-business"],
            },
        )
        self.assertEqual(metadata["publication"], "Music Ally")
        self.assertEqual(metadata["publication_date"], "2026-07-28")
        self.assertIn("platform_economics", metadata["relevance"])
        self.assertTrue(metadata["claims"])

    def test_writer_emits_phase3_frontmatter(self):
        rendered = _render_note({
            "source": "Music Ally",
            "source_url": "https://example.test/article",
            "date": "2026-07-28",
            "title": "Bandcamp changes discovery",
            "observation": "Bandcamp changes discovery.",
            "expanded_context": "The platform changes how listeners find releases.",
            "tags": ["bandcamp"],
            "article_metadata": {"claims": ["The platform changes discovery."], "topics": ["bandcamp"]},
        })
        self.assertIn("publication: \"Music Ally\"", rendered)
        self.assertIn("claims: [\"The platform changes discovery.\"]", rendered)
        self.assertIn("relevance: [platform_economics]", rendered)
        self.assertIn("time_sensitivity: high", rendered)


if __name__ == "__main__":
    unittest.main()
