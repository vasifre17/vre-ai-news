import hashlib
import requests
from bs4 import BeautifulSoup

RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
]


def hash_content(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def fetch_rss_items(limit: int = 10):
    items = []
    for url in RSS_FEEDS:
        try:
            xml = requests.get(url, timeout=15).text
            soup = BeautifulSoup(xml, "xml")
            for it in soup.find_all("item")[:limit]:
                title = (it.title.text if it.title else "").strip()
                link = (it.link.text if it.link else "").strip()
                desc = (it.description.text if it.description else title).strip()
                image = ""
                media = it.find("media:content")
                if media and media.get("url"):
                    image = media["url"]
                items.append({"title": title, "url": link, "content": desc, "image_url": image, "hash": hash_content(title + desc)})
        except Exception:
            continue
    return items
