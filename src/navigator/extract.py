"""HTML -> clean text, title, outgoing links, emails."""
import re
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]


def extract(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("mailto:"):
            continue
        links.append(urldefrag(urljoin(url, href))[0])

    title = (soup.title.get_text(" ", strip=True) if soup.title else "") or url
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for sel in ["[role=navigation]", ".breadcrumb", ".cookie", "#cookie-banner"]:
        for tag in soup.select(sel):
            tag.decompose()
    main = soup.find("main") or soup.find(id="content") or soup.body or soup
    text = re.sub(r"\n\s*\n+", "\n", main.get_text("\n", strip=True))

    emails = sorted(set(EMAIL_RE.findall(html)))
    return {"url": url, "title": title, "text": text, "emails": emails, "links": links}


def chunk(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks
