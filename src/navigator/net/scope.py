"""Scope and URL rules for the net: what may be fetched, and what a link probably leads to.

In scope, as in the challenge brief: every *.unibe.ch site (the inventory is the start of the map,
not its edge; ARTORG is one of them) and Diabetes Center Berne. Nothing else is ever fetched.
Within scope we only collect page kinds that fill a result field: person profiles, people lists,
unit home and about pages, research, project, and infrastructure or service pages.
"""
import re
from urllib.parse import urldefrag, urljoin, urlsplit

from ..discover import EXCLUDE as _DISCOVER_EXCLUDE

IN_SCOPE_HOSTS = {"dcberne.com"}

# portals, intranets, learning platforms, annual reports, the publication repository: no unit content
EXCLUDED_HOSTS = (set(_DISCOVER_EXCLUDE) - {"unibe.ch"}) | {
    "intranet.iml.unibe.ch", "jb2025.iml.unibe.ch", "medposter.iml.unibe.ch", "myalumni.unibe.ch",
    "ksl-vv.unibe.ch", "ksl.unibe.ch", "suche.unibe.ch", "tobira.unibe.ch", "unibern.ch"}
EXCLUDED_HOST_RE = re.compile(
    r"(^|\.)(wiki|intranet|intern|webmail|mail|owa|vpn|login|sso|auth|moodle|ilias|cms|edit|test|dev|staging|preview"
    r"|apps|survey|umfrage|rooms|booking|alumni|kinderuni|seniorenuni|informationskiosk|agenda|ecoach|shop|webshop"
    r"|tickets?|jb\d{4}|ar\d{4}|gb\d{4}|jahresbericht\d{4})[.-]")

# fetch order: the page kinds that fill result fields come first
KIND_PRIORITY = {"profile": 10.0, "people": 9.0, "home": 9.0, "infra": 8.0,
                 "research": 7.0, "project": 7.0, "about": 6.0, "other": 2.0}

SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|svg|webp|ico|zip|docx?|xlsx?|pptx?|pdf|mp4|mp3|wav|ics|vcf|css|js|xml"
                      r"|json|txt|rss)$", re.I)
# page kinds no result field uses: news, events, teaching, publication lists, jobs, legal, media
SKIP_PATH = re.compile(r"""(
    login|logout|/search|/suche|index_print|_fra\.html|/fr/|/it/|sitemap|nav_portal|nav_uniintern|/feed
  | wp-login|wp-admin|wp-json|replytocom|/tag/|/author/|/category/|/page/\d+
  | impressum|imprint|datenschutz|privacy|data[-_]protection|disclaimer|cookie
  | /jobs|/stellen|/job_|career|karriere
  | /news|news_|aktuell|medienmitteilung|/press|/events?[/_]|veranstaltung|agenda|kalender|calendar
  | /studium|/studies|/study[/_]|/studying|/lehre|/teaching|/courses?[/_]|/kurse?[/_]|vorlesung|lecture
  | /master|/bachelor|/doktorat|/weiterbildung|/continuing|newsletter|/archiv|/medien|/media[/_]
  | publikation|publication|/downloads?[/_]|formular|/forms?[/_]|/shop|/alumni|/blog
  | /galler|/galerie|/fotos|/photos|/videos?[/_]|/podcast
)""", re.I | re.X)
# unfilled CMS placeholders ({$uid:...}) and WordPress date archives (/2025/08/)
TEMPLATE_OR_ARCHIVE = re.compile(r"[{}$]|%7b|%24|/\d{4}/\d{2}(/|$)|/\d{4}/?$", re.I)
SKIP_ANCHORS = {"news", "aktuell", "events", "veranstaltungen", "agenda", "jobs", "stellen", "offene stellen",
                "login", "studium", "studies", "lehre", "teaching", "publications", "publikationen", "impressum",
                "newsletter", "media", "medien", "archive", "archiv", "sitemap", "print", "drucken"}

PEOPLE_DIRS = {"people", "personen", "person", "persons", "team", "teams", "staff", "mitarbeitende", "mitarbeiter",
               "mitarbeiterinnen", "members", "mitglieder", "group_members", "groupmembers", "employees",
               "contact", "contacts", "kontakt", "leitung", "direktion", "management", "board", "vorstand",
               "faculty_members", "researchers", "forschende", "ansprechpersonen", "contact_persons", "team_members"}
PEOPLE_ANCHOR = re.compile(r"\b(team|people|personen|mitarbeitende|mitarbeiter\w*|staff|members|mitglieder"
                           r"|ansprechpersonen|contact persons|group members)\b", re.I)
# tokens in UniBE profile slugs, e.g. prof_dr_obrist_dominik, zysset_phd_philippe
_TITLE_TOKENS = {"prof", "dr", "phd", "md", "pd", "msc", "bsc", "em", "dipl", "lic", "dent", "vet", "mlaw",
                 "rer", "nat", "phil", "ing", "mag", "dphil", "mba", "ma", "ba", "med"}
INFRA_RE = re.compile(r"service|dienstleist|angebot|infrastru|facilit|equipment|geraete|geräte|instrument|platform"
                      r"|plattform|core|technolog|labor|/labs?(/|_)|method|analytik|analys|microscop|mikroskop"
                      r"|sequenc|imaging|biobank|offer|consult|beratung|industry|industrie|transfer|innovation"
                      r"|kooperation|collaborat|partner")
PROJECT_RE = re.compile(r"project|projekt")
RESEARCH_RE = re.compile(r"research|forschung|group|gruppe|abteilung|division|/units?(/|_)|bereich|schwerpunkt"
                         r"|topic|themen|expertise|kompetenz|/lab_|_lab(/|$)|clinic|klinik|center|centre|zentrum")
ABOUT_RE = re.compile(r"about|ueber_uns|uber_uns|portrait|organi[sz]ation|institut|wir_ueber")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def in_scope(host: str) -> bool:
    return host == "unibe.ch" or host.endswith(".unibe.ch") or host in IN_SCOPE_HOSTS


def excluded(host: str) -> bool:
    """Excluded hosts, their subdomains (agenda.ub.unibe.ch), and portal-like names (rooms.apps.zmk.unibe.ch)."""
    return (host in EXCLUDED_HOSTS or any(host.endswith("." + h) for h in EXCLUDED_HOSTS)
            or bool(EXCLUDED_HOST_RE.search(host)))


def absolute(href: str, base: str) -> str | None:
    """Resolve a link; None for anchors, mail/phone/script links and overlong URLs."""
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith(("mailto:", "javascript:", "tel:", "data:")):
        return None
    url = urldefrag(urljoin(base, href))[0]
    return url if url.startswith(("http://", "https://")) and len(url) <= 300 else None


def person_slug(url: str) -> str | None:
    """UniBE translates the path (about_us/people <-> ueber_uns/personen) but keeps the person's slug
    (prof_dr_obrist_dominik), so host + slug identifies both language versions of a profile."""
    segs = [s for s in urlsplit(url).path.lower().split("/") if s]
    if segs and "." in segs[-1]:
        segs = segs[:-1]
    return segs[-1] if segs and _is_person_slug(segs[-1]) else None


def _is_person_slug(seg: str) -> bool:
    tokens = re.split(r"[_\-]", seg)
    titles = sum(t in _TITLE_TOKENS for t in tokens)
    return titles >= 1 and len(tokens) - titles >= 2 and not any(c.isdigit() for c in seg)


def classify(url: str, anchor: str = "") -> str:
    """Guess the page kind from the URL and link text, before fetching. 'skip' = never fetch."""
    parts = urlsplit(url)
    path = parts.path.lower()
    anchor_low = anchor.lower().strip()
    if parts.query or SKIP_EXT.search(path) or SKIP_PATH.search(path) or path.endswith("/index.html") \
            or anchor_low in SKIP_ANCHORS or TEMPLATE_OR_ARCHIVE.search(path):
        return "skip"
    segs = [s for s in path.split("/") if s]
    if segs and "." in segs[-1]:
        segs = segs[:-1]  # index_eng.html and friends
    if not segs:
        return "home"
    if any(_is_person_slug(s) for s in segs):
        return "profile"
    if segs[-1] in PEOPLE_DIRS or PEOPLE_ANCHOR.search(anchor_low):
        return "people"
    if any(s in PEOPLE_DIRS for s in segs[:-1]):
        return "profile"  # e.g. /team/firstname-lastname/
    text = path + " " + anchor_low
    if INFRA_RE.search(text):
        return "infra"
    if PROJECT_RE.search(text):
        return "project"
    if RESEARCH_RE.search(text):
        return "research"
    if ABOUT_RE.search(text):
        return "about"
    return "other"
