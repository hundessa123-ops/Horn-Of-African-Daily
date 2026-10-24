
import hashlib
import os
import re
import html
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import feedparser

# Add verified RSS feed URLs here in the next step.

RSS_SOURCES = [
    "https://news.google.com/rss/search?q=Ethiopia+politics&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Ethiopia+diplomacy&hl=en-US&gl=US&ceid=US:en",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
]


# Only add domains after confirming they are official government sites.
OFFICIAL_DOMAINS = [
    # Example: "mfa.gov.et"
]

MAX_POSTS = 10
MIN_MATCHES = 2
OUTPUT_PATH = "docs/feed.xml"


def get_domain(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(value).split())


def is_official(domain):
    return any(
        domain == trusted or domain.endswith("." + trusted)
        for trusted in OFFICIAL_DOMAINS
        if trusted
    )


def main():
    grouped = {}

    for feed_url in RSS_SOURCES:
        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and not feed.entries:
                print("Could not read feed:", feed_url)
                continue

            for entry in feed.entries:
                link = entry.get("link", "").strip()
                title = clean_text(entry.get("title", ""))
                summary = clean_text(
                    entry.get("summary", entry.get("description", ""))
                )

                if not link or not title:
                    continue

                domain = get_domain(link)
                if not domain or urlparse(link).scheme != "https":
                    continue

                # Group exact URLs. Different URLs about the same event
                # are not automatically considered independent verification.
                key = hashlib.sha256(link.encode("utf-8")).hexdigest()

                if key not in grouped:
                    grouped[key] = {
                        "title": title,
                        "link": link,
                        "summary": summary,
                        "domains": set(),
                        "published": entry.get("published", ""),
                    }

                grouped[key]["domains"].add(domain)

                if not grouped[key]["summary"] and summary:
                    grouped[key]["summary"] = summary

        except Exception as exc:
            print("Feed error:", feed_url, str(exc))

    posts = []

    for item in grouped.values():
        # An official-domain match is a source classification, not proof
        # that every claim in the story is independently verified.
        if not (
            is_official(get_domain(item["link"]))
            or len(item["domains"]) >= MIN_MATCHES
        ):
            continue

        text = item["summary"]
        if not text:
            print("Skipped item with no summary:", item["title"])
            continue

        # Avoid implying that truncation is a complete summary.
        words = text.split()
        if len(words) > 75:
            text = " ".join(words[:75]).rstrip(" ,;:") + "..."

        # Headline + body + source URL must fit within 100 words.
        headline = item["title"]
        post_text = f"{headline}\n\n{text}\n\nSource: {item['link']}"

        if len(post_text.split()) > 100:
            available = max(10, 95 - len(headline.split())
                            - len(item["link"].split()))
            text = " ".join(text.split()[:available]).rstrip(" ,;:") + "..."
            post_text = f"{headline}\n\n{text}\n\nSource: {item['link']}"

        posts.append({
            "title": headline,
            "text": post_text,
            "link": item["link"],
            "guid": hashlib.sha256(
                item["link"].encode("utf-8")
            ).hexdigest(),
        })

    posts = posts[:MAX_POSTS]

    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = (
        "Horn African Daily - News Feed"
    )
    ET.SubElement(channel, "link").text = (
        "https://example.com/"
    )
    ET.SubElement(channel, "description").text = (
        "News feed for Horn African Daily. Items require review."
    )
    ET.SubElement(channel, "language").text = "en"

    now = format_datetime(datetime.now(timezone.utc))

    for post in posts:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = post["title"]
        ET.SubElement(item, "description").text = post["text"]
        ET.SubElement(item, "link").text = post["link"]
        ET.SubElement(item, "guid", isPermaLink="false").text = post["guid"]
        ET.SubElement(item, "pubDate").text = now

    os.makedirs("docs", exist_ok=True)
    ET.ElementTree(root).write(
        OUTPUT_PATH, encoding="utf-8", xml_declaration=True
    )

    print(f"Created {OUTPUT_PATH}: {len(posts)} candidate posts")
    if not posts:
        print("No items passed the filters. Check RSS sources and logs.")


if __name__ == "__main__":
    main()
