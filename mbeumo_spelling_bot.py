#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

import praw

MISSPELLINGS_RAW: list[str] = [
    r"\bmbuemo\b",
    r"\bmbeuemo\b",
    r"\bmbeuomo\b",
    r"\bmbeuono\b",
    r"\bmbeoumo\b",
    r"\bmboomo\b",
    r"\bmbeemo\b",
    r"\bmbeuno\b",
    r"\bmeubomo\b",
    r"\bmboma\b",
    r"\bmbumeo\b",
    r"\bmbewmoe\b",
    
]
MISSPELLINGS: list[re.Pattern[str]] = [re.compile(pat, re.I) for pat in MISSPELLINGS_RAW]

CORRECT_NAME = "Mbeumo"
STATS_PATH = Path("/data/stats.json")

LIMIT_TO_SUBMISSION_TITLED = os.getenv("LIMIT_TO_SUBMISSION_TITLED")

REPLY_TEMPLATE = (
    "👋 Just a quick heads‑up — I think you meant **{correct}**, not “{found}”. " \
    "\n\n---\n\n*^(If you want to know how to pronounce em-ber-mo's name [here is a Youtube link](https://youtube.com/shorts/pocySXnRwl8?si=2a0UE1vqdANWHT6Q) "
    "of him saying it)*"
)

# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def load_stats() -> dict:
    if STATS_PATH.exists():
        try:
            with STATS_PATH.open() as f:
                data = json.load(f)
            data.setdefault("start_time", datetime.now(timezone.utc).isoformat())
            data.setdefault("total_corrections", 0)
            data.setdefault("misspellings", {})
            return data
        except Exception:
            pass  # fall through to fresh stats
    return {
        "start_time": datetime.now(timezone.utc).isoformat(),
        "total_corrections": 0,
        "misspellings": {},
    }


def save_stats(stats: dict) -> None:
    try:
        with STATS_PATH.open("w") as f:
            json.dump(stats, f, indent=2)
    except Exception as exc:
        print(f"[STATS] Failed to save: {exc}")


STATS = load_stats()

# ---------------------------------------------------------------------------
# Comment processing
# ---------------------------------------------------------------------------

def find_misspelling(text: str) -> str | None:
    """Return the exact misspelling found, or None."""
    # If the correct spelling appears, ignore.
    if re.search(rf"\b{CORRECT_NAME}\b", text, re.I):
        return None
    for pat in MISSPELLINGS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None

def main() -> None:
    load_dotenv()

    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=f"mbeumobot (by u/{os.environ['REDDIT_AUTHOR_USERNAME']}) - https://github.com/ccameronmills/mbeumo-bot",
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
    )

    poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
    if poll_interval < 10:
        print("[WARN] POLL_INTERVAL_SECONDS too low; setting to 10s to respect API.")
        poll_interval = 10

    subreddit_names = os.getenv("SUBREDDITS", "reddevils").replace(",", "+")
    subreddit = reddit.subreddit(subreddit_names)

    print(
        f"[BOT] Watching r/{subreddit_names} every {poll_interval}s. "
        f"Corrections so far: {STATS['total_corrections']}."
    )

    def graceful_exit(*_: object) -> None:
        print("\n[BOT] Shutting down – saving stats…")
        save_stats(STATS)
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_exit)
    signal.signal(signal.SIGTERM, graceful_exit)

    # Stream with pause_after to yield None when caught up
    comment_stream = subreddit.stream.comments(pause_after=0, skip_existing=True)

    while True:
        try:
            for comment in comment_stream:
                if comment is None:
                    # No new comments – sleep to reduce API calls
                    time.sleep(poll_interval)
                    break

                STATS.setdefault("misspellings", {})  # for safety

                if LIMIT_TO_SUBMISSION_TITLED:
                    # Normalize both title and filter for case-insensitive matching
                    thread_title = (comment.submission.title or "").lower()
                    if LIMIT_TO_SUBMISSION_TITLED.lower() not in thread_title:
                        continue

                # Ignore self
                if comment.author and comment.author.name.lower() == reddit.user.me().name.lower():
                    continue

                misspelling = find_misspelling(comment.body)
                if misspelling is None or comment.saved:
                    continue

                # Reply
                reply_text = REPLY_TEMPLATE.format(correct=CORRECT_NAME, found=misspelling)
                comment.reply(reply_text)
                comment.save()

                # Update stats
                STATS["total_corrections"] += 1
                STATS["misspellings"].setdefault(misspelling.lower(), 0)
                STATS["misspellings"][misspelling.lower()] += 1
                save_stats(STATS)

                print(
                    f"[BOT] Corrected '{misspelling}' (total corrections: {STATS['total_corrections']})"
                )

        except Exception as exc:
            print(f"[ERROR] {exc}. Sleeping 60 s…")
            time.sleep(60)


if __name__ == "__main__":
    main()
