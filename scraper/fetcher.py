import hashlib
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = "VREYCNewsBot/1.0 (+https://vreyc.com)"
REQUEST_TIMEOUT = 20

SOURCES = [
    {
        "key": "qafqazinfo",
        "name": "Qafqazinfo",
        "url": "https://qafqazinfo.az/",
        "article_marker": "/news/detail/",
    },
    {
        "key": "azertac",
        "name": "AZƏRTAC",
        "url": "https://special.azertag.az/az",
        "article_marker": "/az/xeber/",
    },
]

CATEGORY_MAP = {
    "siyasət": "Politics",
    "dünya": "World",
    "iqtisadiyyat": "Economy",
    "biznes": "Business",
    "idman": "Sports",
    "sağlamlıq": "Health",
    "ölkə": "Country",
    "cəmiyyət": "Country",
    "regionlar": "Country",
    "hadisə": "Incident",
    "kriminal": "Incident",
    "elm": "Science and Education",
    "təhsil": "Science and Education",
    "mədəniyyət": "Show Business",
    "şou": "Show Business",
}

BODY_SELECTORS = [
    '[itemprop="articleBody"]',
    '.news_text',
    '.news-text',
    '.article-content',
    '.article_content',
    '.detail-content',
    '.detail__content',
    '.post-content',
    'article',
]


def hash_content(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "az,en;q=0.8",
    })
    return session


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = re.sub(r"/+", "/", parsed.path or "/")
    return f"https://{host}{path}".rstrip("/")


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _clean_content(container) -> str:
    fragment = BeautifulSoup(str(container), "html.parser")
    for selector in ("script", "style", "noscript", "iframe", "form", ".reklam", ".advertisement", ".share", ".social", ".related"):
        for node in fragment.select(selector):
            node.decompose()
    for node in fragment.find_all(True):
        for attr in list(node.attrs):
            if attr.lower().startswith("on") or attr.lower() in {"style", "class", "id", "srcset", "data-srcset"}:
                node.attrs.pop(attr, None)
        if node.name == "a" and str(node.get("href", "")).lower().startswith("javascript:"):
            node.unwrap()
    root = fragment.find()
    return "".join(str(child) for child in root.contents).strip() if root else ""


def _article_body(soup: BeautifulSoup) -> str:
    for selector in BODY_SELECTORS:
        container = soup.select_one(selector)
        if container and len(container.get_text(" ", strip=True)) >= 120:
            return _clean_content(container)

    main = soup.find("main") or soup.body
    if main:
        paragraphs = [str(p) for p in main.find_all("p") if len(p.get_text(" ", strip=True)) >= 20]
        if len(BeautifulSoup("".join(paragraphs), "html.parser").get_text(" ", strip=True)) >= 120:
            return "\n".join(paragraphs)
    return ""


def _published_at(soup: BeautifulSoup) -> datetime | None:
    raw = _meta(soup, "article:published_time", "datePublished", "pubdate", "publish-date")
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

    text = soup.get_text(" ", strip=True)
    for pattern, fmt in (
        (r"(\d{2}\.\d{2}\.\d{4})\s*(\d{2}:\d{2})", "%d.%m.%Y %H:%M"),
        (r"(\d{4}-\d{2}-\d{2})\s*(\d{2}:\d{2})(?::\d{2})?", "%Y-%m-%d %H:%M"),
    ):
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(f"{match.group(1)} {match.group(2)}", fmt)
            except ValueError:
                pass
    return None


def _category(soup: BeautifulSoup) -> str:
    raw = _meta(soup, "article:section")
    if not raw:
        breadcrumb = soup.select_one(".breadcrumb, .breadcrumbs")
        raw = breadcrumb.get_text(" ", strip=True) if breadcrumb else ""
    folded = raw.casefold()
    for needle, category in CATEGORY_MAP.items():
        if needle in folded:
            return category
    return "Country"


def _discover_urls(session: requests.Session, source: dict, limit: int) -> list[str]:
    try:
        response = session.get(source["url"], timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    expected_host = urlparse(source["url"]).netloc.lower().replace("www.", "")
    urls, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        url = _canonical_url(urljoin(source["url"], anchor["href"]))
        parsed = urlparse(url)
        if parsed.netloc.lower().replace("www.", "") != expected_host:
            continue
        if source["article_marker"] not in parsed.path or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _fetch_article(session: requests.Session, source: dict, url: str) -> dict | None:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    title = _meta(soup, "og:title", "twitter:title") or (soup.h1.get_text(" ", strip=True) if soup.h1 else "")
    content = _article_body(soup)
    plain = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
    if len(title.strip()) < 5 or len(plain) < 120:
        return None

    canonical_tag = soup.find("link", rel="canonical")
    canonical = _canonical_url(urljoin(url, canonical_tag.get("href", ""))) if canonical_tag and canonical_tag.get("href") else _canonical_url(url)
    image_url = _meta(soup, "og:image", "twitter:image")
    image_url = urljoin(url, image_url) if image_url else ""
    summary = _meta(soup, "description", "og:description")
    if not summary:
        first_p = BeautifulSoup(content, "html.parser").find("p")
        summary = first_p.get_text(" ", strip=True) if first_p else plain[:300]

    return {
        "source_key": source["key"],
        "source_name": source["name"],
        "title": title.strip(),
        "url": canonical,
        "content": content,
        "summary": summary.strip(),
        "image_url": image_url,
        "category": _category(soup),
        "published_at": _published_at(soup),
        "hash": hash_content(f'{source["key"]}|{canonical}'),
    }


def fetch_rss_items(limit: int = 12):
    """Fetch recent Azerbaijani articles without AI rewriting.

    The legacy function name remains so the existing scheduler needs no API change.
    """
    session = _session()
    items = []
    for source in SOURCES:
        for url in _discover_urls(session, source, limit):
            item = _fetch_article(session, source, url)
            if item:
                items.append(item)
    items.sort(key=lambda item: item.get("published_at") or datetime.min, reverse=True)
    return items
