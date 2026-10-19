"""Read one fetched page: its type, how relevant it is, its links, and the people and unit it shows.

A pure function of (html, url), so the seed step can run it in a process pool. UniBE pages share one
CMS template: a profile is article.team-detail and a list entry is article.team-box, both with
schema.org Person microdata, so people are read from the markup rather than guessed. A field is kept
only if its text appears on the page, and it carries that text as its evidence quote.
"""
import re
from collections import Counter

from bs4 import BeautifulSoup

from .scope import absolute, classify

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe"]
CMS_CLIENT_RE = re.compile(r'class="[^"]*\bclient-([a-z0-9_]+)')
CMS_PATH_RE = re.compile(r"/unibe/portal/((?:[a-z0-9_]+/){0,3}?[a-z0-9_]+)/(?:content|e\d+)/")
TARGET_WORDS = re.compile(r"team|people|personen|mitarbeitende|staff|research|forschung|expertise|service"
                          r"|dienstleistung|infrastru|equipment|geräte|facilit|platform|plattform|labor|project"
                          r"|projekt|kooperation|collaborat|industry|technolog|method|analys", re.I)
RELEVANCE = {"person_profile": 1.0, "people_list": 0.9, "profile": 0.8, "infra": 0.8, "people": 0.7,
             "research": 0.7, "project": 0.7, "home": 0.6, "about": 0.6, "other": 0.3}
KEEP_THRESHOLD = 0.5
INTEREST_LABELS = ("research interest", "forschungsinteresse", "forschungsschwerpunkt", "research focus",
                   "research topic", "schwerpunkt", "expertise", "research", "forschung")
NAME_TITLES = {"prof", "dr", "pd", "em", "med", "dent", "vet", "phil", "rer", "nat", "habil", "dipl", "ing",
               "dipling", "lic", "mag", "msc", "bsc", "ma", "ba", "phd", "md", "mba", "iur", "oec", "pharm", "sc",
               "dres", "hc", "univ", "mas", "fmh"}
ID_LINK_RE = re.compile(r"orcid\.org/|scholar\.google|researchgate\.net/profile|linkedin\.com/in/", re.I)


def decode(raw: bytes) -> str:
    """UniBE serves both UTF-8 and Latin-1 pages."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _txt(el) -> str:
    return _norm(el.get_text(" ")) if el is not None else ""


def clean_name(raw: str) -> str:
    """'Prof. Dr. Dominik Obrist' -> 'Dominik Obrist'; 'Philippe Zysset, PhD' -> 'Philippe Zysset'."""
    tokens = raw.split(",")[0].split()
    key = lambda t: t.lower().replace(".", "").replace("-", "")
    while len(tokens) > 2 and key(tokens[0]) in NAME_TITLES:
        tokens.pop(0)
    while len(tokens) > 2 and key(tokens[-1]) in NAME_TITLES:
        tokens.pop()
    return " ".join(tokens)


def _verified(fields: dict, text: str, url: str) -> dict:
    """Keep only values found verbatim in the page text; each kept value becomes an evidence quote."""
    data, evidence = {}, []
    for k, v in fields.items():
        if isinstance(v, list):
            keep = list(dict.fromkeys(x for x in v if x and x in text))
            data[k] = keep
            evidence += [{"field": k, "quote": x, "url": url} for x in keep]
        elif v and v in text:
            data[k] = v
            evidence.append({"field": k, "quote": v, "url": url})
        else:
            data[k] = ""
    data["evidence"] = evidence
    return data


def _email(el) -> str:
    """The address as written on the page (the evidence quote); get_text decodes UniBE's &#x..; entities."""
    e = _txt(el)
    return e if EMAIL_RE.match(normalize_email(e)) else ""


def normalize_email(e: str) -> str:
    """'lars.straub(a)unibe.ch' -> 'lars.straub@unibe.ch'."""
    return re.sub(r"\s*(\(a\)|\[at\]|\(at\)|\[a\])\s*", "@", e.strip(), flags=re.I).lower()


def _finish(person: dict) -> dict:
    """Verified fields keep the on-page spelling as evidence; the email value itself is normalised."""
    if person.get("email"):
        person["email"] = normalize_email(person["email"])
    return person


def _tabs(soup) -> dict:
    """Profile tabs (CV, Research Interests, Publications, ...): lower-case label -> panel element."""
    labels = {li.get("id"): _txt(li).lower() for li in soup.select('li[role="tab"]') if li.get("id")}
    panels = {}
    for p in soup.select('[role="tabpanel"]'):
        label = labels.get(p.get("aria-labelledby"), "")
        if label and label not in panels:
            panels[label] = p
    return panels


def _items(panel, label: str) -> list[str]:
    lis = [x for x in (_txt(li) for li in panel.find_all("li")) if 2 < len(x) <= 150]
    if len(lis) < 2:
        lis = [x for x in (_norm(s) for s in panel.get_text("\n").split("\n")) if 2 < len(x) <= 150]
    return [x for x in dict.fromkeys(lis) if x.lower() != label][:40]


def _profile(soup, art, url: str, text: str) -> dict:
    job_el = art.select_one('[itemprop="jobTitle"]')
    aff_el = job_el.find_next_sibling("p") if job_el is not None else None
    if aff_el is not None and aff_el.has_attr("itemprop"):
        aff_el = None
    name = _txt(art.select_one('[itemprop="name"]'))
    phones = [_txt(x) for x in art.select('[itemprop="telephone"]')]
    tabs = _tabs(soup)
    interests, research_text, projects = [], "", []
    for want in INTEREST_LABELS:
        label = next((l for l in tabs if want in l and "publi" not in l), None)
        if label:
            interests = _items(tabs[label], label)
            research_text = _txt(tabs[label])[:1500]
            break
    proj_label = next((l for l in tabs if "project" in l or "projekt" in l), None)
    if proj_label:
        projects = _items(tabs[proj_label], proj_label)
    # free-text intro between the header block and the tabs, and the text of the other tabs (not publications)
    summary = []
    for el in art.find_all_next(["p", "li", "div", "h2", "ul"], limit=80):
        if el.name == "ul" and "nav-tabs" in el.get("class", []) or el.get("role") == "tablist":
            break
        if el.name == "p" and not el.find_parent("article", class_="team-detail"):
            t = _txt(el)
            if len(t) >= 60:
                summary.append(t[:1500])
    summary += [_txt(p)[:1500] for label, p in tabs.items() if "publi" not in label and len(_txt(p)) >= 60]
    ids = sorted({a["href"] for a in soup.find_all("a", href=True) if ID_LINK_RE.search(a["href"])})
    person = _verified({"name": name, "name_clean": clean_name(name), "role": _txt(job_el),
                        "affiliation": _txt(aff_el), "email": _email(art.select_one('[itemprop="email"]')),
                        "phone": phones[0] if phones else "", "address": _txt(art.select_one('[itemprop="worksFor"]')),
                        "expertise": interests, "research_text": research_text, "projects": projects,
                        "summary": summary[:6]}, text, url)
    person.update(kind="profile", profile_url=url, identifiers=ids[:10])
    return _finish(person)


def _list_entry(art, url: str, text: str) -> dict | None:
    link = next((a for a in art.find_all("a", href=True)
                 if not a["href"].strip().lower().startswith(("javascript:", "mailto:", "tel:"))), None)
    name = _txt(art.select_one('[itemprop="name"]')) or _txt(link)
    if not name:
        return None
    person = _verified({"name": name, "name_clean": clean_name(name),
                        "role": _txt(art.select_one('.jobTitle, [itemprop="jobTitle"]')),
                        "email": _email(art.select_one('[itemprop="email"]')),
                        "phone": _txt(art.select_one('[itemprop="telephone"]')),
                        "group": _txt(art.find_previous(["h2", "h3"]))}, text, url)
    person.update(kind="list", list_url=url, profile_url=absolute(link["href"], url) if link else None)
    return _finish(person)


def _card_people(soup, url: str, text: str, html: str) -> list[dict]:
    """Diabetes Center Berne (WordPress/Divi): each person is a card with a role line, the name in an h2
    and a mailto link, under group headings such as 'Core Team Clinical' or 'Sensing & Monitoring Lab'."""
    people, group = [], ""
    for h in soup.find_all(["div", "h1", "h2", "h3", "h4"]):
        if h.name == "div":  # group titles are short text modules between the cards
            t = _txt(h) if "et_pb_text_inner" in h.get("class", []) else ""
            if 0 < len(t) <= 80 and not re.search(r"https?://|www\.|\.(org|ch|com)\b|visit", t, re.I):
                group = t
            continue
        card = h.find_parent(class_="et_pb_de_mach_content")
        if card is None:
            group = _txt(h) or group
            continue
        mail = card.find("a", href=re.compile(r"^mailto:", re.I))
        role_el = h.find_previous_sibling("p")
        name = _txt(h)
        if not name or len(name) > 80:
            continue
        person = _verified({"name": name, "name_clean": clean_name(name), "role": _txt(role_el), "group": group},
                           text, url)
        email = mail["href"][7:].split("?")[0].strip() if mail else ""
        if email and EMAIL_RE.match(email) and email in html:  # in the page source, behind the 'Mail' link
            person["email"] = email.lower()
            person["evidence"].append({"field": "email", "quote": email, "url": url, "where": "mailto link"})
        else:
            person["email"] = ""
        person.update(kind="list", list_url=url, profile_url=None)
        people.append(person)
    return people


def process(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = _txt(soup.title)
    text = _norm(soup.get_text(" "))  # whole page, used to verify quotes

    persons = []
    detail = soup.select_one("article.team-detail")
    if detail is not None:
        persons.append(_profile(soup, detail, url, text))
    entries = [p for p in (_list_entry(a, url, text) for a in soup.select("article.team-box")) if p]
    if "et_pb_de_mach_content" in html:
        entries += _card_people(soup, url, text, html)
    persons += entries
    profile_links = {p["profile_url"] for p in entries if p.get("profile_url")}

    links = []
    for a in soup.find_all("a", href=True):
        u = absolute(a["href"], url)
        if u:
            links.append((u, _txt(a)[:80], "profile" if u in profile_links else None))

    cms_paths = Counter(CMS_PATH_RE.findall(html))
    client = CMS_CLIENT_RE.search(html)
    area = _txt(soup.select_one(".area-title"))
    unit = _verified({"name": area}, text, url) if area else {}
    unit.update(cms_client=client.group(1) if client else "",
                cms_path=cms_paths.most_common(1)[0][0] if cms_paths else "")

    headings = " ".join(_txt(h) for h in soup.find_all(["h1", "h2"])[:20])
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    main = soup.find("main") or soup.find(id="content") or soup.body or soup
    main_chars = len(_norm(main.get_text(" ")))

    if detail is not None:
        page_type = "person_profile"
    elif entries or html.count("schema.org/Person") >= 2:
        page_type = "people_list"
    else:
        kind = classify(url)
        page_type = "other" if kind == "skip" else kind
    relevance = RELEVANCE[page_type] + min(0.2, 0.05 * len(TARGET_WORDS.findall(title + " " + headings)))
    if main_chars < 200 and page_type not in ("person_profile", "people_list"):
        relevance = min(relevance, 0.2)  # menu, redirect or script-only page
    relevance = round(min(relevance, 1.0), 3)
    return {"page_type": page_type, "relevance": relevance, "kept": relevance >= KEEP_THRESHOLD,
            "title": title, "text_chars": main_chars, "links": links, "persons": persons, "unit": unit}
