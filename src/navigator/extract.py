"""HTML -> clean text, title, outgoing links, emails."""
import re
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup, NavigableString

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]


def extract(html: str, url: str, *, paragraphs: bool = False) -> dict:
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
    if paragraphs:
        for tag in soup.select("aside, #sidebar, .sidebar, .widget, .related-posts, .et_pb_blog_grid_wrapper"):
            tag.decompose()
    main = soup.find("main") or soup.find(id="content") or soup.find(id="main-content") or soup.body or soup
    if paragraphs:
        if main.h1:
            heading = main.h1.get_text(" ", strip=True)
            if heading and not re.fullmatch(r"navigation|menu|main menu", heading, re.I):
                title = heading
        # Inline links/emphasis must not split a sentence into unrelated passages.
        for node in list(main.descendants):
            if isinstance(node, NavigableString):
                node.replace_with(re.sub(r"\s+", " ", str(node)))
        for tag in main.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "dt", "dd", "blockquote", "br"]):
            tag.insert_before("\x1e" if tag.name.startswith("h") and tag.name[1:].isdigit() else "\n")
            tag.insert_after("\n")
        # Keep heading boundaries separate from paragraph/list-item boundaries.
        # The temporary marker is removed before text reaches a finding.
        sections = []
        for section in main.get_text(" ", strip=False).split("\x1e"):
            lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in section.splitlines()]
            sections.append("\n".join(line for line in lines if line))
        text = "\n\n".join(section for section in sections if section)
    else:
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
