
import os
import re
import html
import hashlib
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import feedparser

RSS_SOURCES = [
    "https://news.google.com/rss/search?q=Ethiopia+politics&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Ethiopia+diplomacy&hl=en-US&gl=US&ceid=US:en",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]

MAX_POSTS = 10
MIN_MATCHES = 2
MAX_AGE_HOURS = 48
OUTPUT_PATH = "docs/feed.xml"


def clean(value):
    value = re.sub(r"<[^>]*>", " ", value or "")
    return " ".join(html.unescape(value).split())


def domain(url):
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def normalize_title(title):
    title = clean(title).lower()
    return re.sub(r"[^a-z0-9 ]", " ", title).strip()


def similar(a, b):
    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return False

    ratio = SequenceMatcher(None, a, b).ratio()
    wa, wb = set(a.split()), set(b.split())
    overlap = len(wa & wb) / max(1, len(wa | wb))

    return ratio >= 0.72 or overlap >= 0.60


def main():
    articles = []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)

    for feed_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(feed_url)

            print(
                f"Feed: {feed_url} | "
                f"Entries: {len(feed.entries)}"
            )

            for entry in feed.entries:
                link = entry.get("link", "").strip()
                title = clean(entry.get("title", ""))
                summary = clean(
                    entry.get("summary", entry.get("description", ""))
                )

                if not link or not title:
                    continue

                if urlparse(link).scheme != "https":
                    continue

                # Google News often provides the original publisher
                # in the entry's source metadata.
                source_info = entry.get("source", {})
                source_url = source_info.get("href", "")
                publisher = domain(source_url) if source_url else domain(link)

                if not publisher:
                    continue

                # Do not count Google News itself as a news publisher.
                if publisher in ("news.google.com", "google.com"):
                    continue

                published = entry.get("published_parsed")
                if published:
                    import calendar
                    published_dt = datetime.fromtimestamp(
                        calendar.timegm(published), tz=timezone.utc
                    )
                    if published_dt < cutoff or published_dt > now + timedelta(hours=2):
                        continue
                else:
                    # Conservative policy: skip undated items.
                    print("Skipped undated article:", title)
                    continue

                articles.append({
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "publisher": publisher,
                    "published": published_dt,
                })

        except Exception as exc:
            print("Feed error:", feed_url, str(exc))

    # Cluster similar headlines. Similarity alone is imperfect and
    # does not establish that the claims in an article are true.
    clusters = []

    for article in sorted(
        articles, key=lambda x: x["published"], reverse=True
    ):
        matched_cluster = None

        for cluster in clusters:
            if similar(article["title"], cluster[0]["title"]):
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append([article])
        else:
            matched_cluster.append(article)

    candidates = []

    for cluster in clusters:
        publishers = {a["publisher"] for a in cluster}

        # Require independent publisher domains.
        if len(publishers) < MIN_MATCHES:
            continue

        # Keep only one article per publisher in a cluster.
        distinct = {}
        for article in cluster:
            distinct.setdefault(article["publisher"], article)

        evidence = list(distinct.values())[:3]

        # Prefer the clearest available RSS summary.
        best = max(evidence, key=lambda a: len(a["summary"]))
        if not best["summary"]:
            print("Skipped without summary:", best["title"])
            continue

        headline = best["title"]
        body_words = best["summary"].split()

        source_text = "Sources: " + " ".join(
            article["link"] for article in evidence[:2]
        )

        # Enforce a maximum of 100 total words.
        fixed_words = len(headline.split()) + len(source_text.split())
        available = max(0, 100 - fixed_words - 1)
        body = " ".join(body_words[:available])

        if len(body_words) > available and available:
            body = body.rstrip(" ,;:") + "..."

        post_text = f"{headline}\n\n{body}\n\n{source_text}"

        if len(post_text.split()) > 100:
            continue

        stable_id = hashlib.sha256(
            normalize_title(headline).encode("utf-8")
        ).hexdigest()

        candidates.append({
            "title": headline,
            "text": post_text,
            "link": best["link"],
            "guid": stable_id,
            "published": best["published"],
        })

    candidates.sort(key=lambda x: x["published"], reverse=True)
    candidates = candidates[:MAX_POSTS]

    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = "Horn African Daily"
    ET.SubElement(channel, "link").text = (
        "https://example.com/"
    )
    ET.SubElement(channel, "description").text = (
        "News candidates from multiple publishers; "
        "automated matching is not a guarantee of accuracy."
    )
    ET.SubElement(channel, "language").text = "en"

    for post in candidates:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = post["title"]
        ET.SubElement(item, "description").text = post["text"]
        ET.SubElement(item, "link").text = post["link"]
        ET.SubElement(item, "guid", isPermaLink="false").text = post["guid"]
        ET.SubElement(item, "pubDate").text = format_datetime(
            post["published"]
        )

    os.makedirs("docs", exist_ok=True)
    ET.ElementTree(root).write(
        OUTPUT_PATH, encoding="utf-8", xml_declaration=True
    )

    print(f"Candidate posts generated: {len(candidates)}")
    print(f"RSS written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
