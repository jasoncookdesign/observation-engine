from __future__ import annotations
"""
Reddit adapter for the Music Culture Observation Engine.
Uses PRAW (Python Reddit API Wrapper) with a read-only OAuth app.

Setup: Create a Reddit "script" app at https://www.reddit.com/prefs/apps
and add client_id / client_secret to the instance config under sources.reddit.
"""

import logging
import os
from datetime import datetime, timezone

import praw
from praw.exceptions import PRAWException

logger = logging.getLogger(__name__)

USER_AGENT = "script:JasonOS.ObservationEngine:v1.0 (by u/jcduser01)"


def fetch(config: dict) -> list[dict]:
    """
    Fetch top posts from each subreddit in config['subreddits'].

    Config keys (under sources.reddit):
      client_id     (str)  — Reddit app client ID
      client_secret (str)  — Reddit app client secret
      subreddits    (list) — subreddit names
      post_limit    (int)  — posts per subreddit (default 25)
      min_score     (int)  — minimum upvote score (default 0)
    """
    client_id = config.get("client_id") or os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = config.get("client_secret") or os.environ.get("REDDIT_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        logger.error(
            "Reddit adapter: client_id and client_secret are required. "
            "Set them in the config under sources.reddit or via "
            "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET environment variables."
        )
        return []

    subreddits = config.get("subreddits", [])
    post_limit = int(config.get("post_limit", 25))
    min_score = int(config.get("min_score", 0))

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=USER_AGENT,
        )
        reddit.read_only = True
    except Exception as exc:
        logger.error("PRAW init error: %s", exc)
        return []

    results = []
    seen_urls: set = set()

    for subreddit_name in subreddits:
        try:
            sub = reddit.subreddit(subreddit_name)
            posts = list(sub.top(time_filter="day", limit=post_limit))
        except PRAWException as exc:
            logger.error("PRAW error for r/%s: %s", subreddit_name, exc)
            continue
        except Exception as exc:
            logger.error("Reddit fetch error for r/%s: %s", subreddit_name, exc)
            continue

        for post in posts:
            try:
                if post.score < min_score:
                    continue

                permalink = f"https://www.reddit.com{post.permalink}"
                if permalink in seen_urls:
                    continue
                seen_urls.add(permalink)

                selftext = (post.selftext or "").strip()
                if selftext:
                    body = selftext[:500]
                else:
                    body = (
                        f"Posted in r/{subreddit_name} with {post.score} upvotes. "
                        f"Link: {post.url}"
                    )[:500]

                try:
                    published_date = datetime.fromtimestamp(
                        post.created_utc, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                except Exception:
                    published_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                raw_tags = [subreddit_name]
                if post.link_flair_text:
                    raw_tags.append(
                        post.link_flair_text.lower().replace(" ", "-")
                    )

                results.append({
                    "source": f"Reddit/r/{subreddit_name}",
                    "source_url": permalink,
                    "title": post.title,
                    "body": body,
                    "published_date": published_date,
                    "raw_tags": raw_tags,
                })
            except Exception as exc:
                logger.error("Error processing post in r/%s: %s", subreddit_name, exc)
                continue

    return results
