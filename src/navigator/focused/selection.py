"""Strict parsing and source-grounded acceptance gates for rule-selected candidates."""
import re
import unicodedata
from collections import Counter
from urllib.parse import urlsplit

from pydantic import ValidationError

from .keywords import record_keywords
from .models import Candidate, Document, GROUPS
from .ranking import score_record, SELECTION_VERSION
from .privacy import has_contact
from .rules import RULESET_VERSION, evaluate
from .web import normalize_url, host


def whitespace(text: str) -> str:
    return " ".join(text.split())


def identity_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"[^\w]+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def validate_findings(raw: dict, document: Document) -> tuple[list[dict], Counter]:
    """Validate each candidate independently; never manufacture fallback findings."""
    rejected = Counter()
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list) or len(raw["findings"]) > 10:
        return [], Counter({"invalid_response": 1})
    text = whitespace(document.title + "\n" + document.text)
    accepted = []
    aliases = {"University of Bern": ("university of bern", "universität bern", "universite de berne", "université de berne", "unibe"),
               "ARTORG": ("artorg",), "Diabetes Center Berne": ("diabetes center berne", "diabetes center bern", "dcb")}
    for item in raw["findings"]:
        try:
            candidate = Candidate.model_validate(item)
        except (ValidationError, TypeError):
            rejected["invalid_candidate"] += 1
            continue
        scores = candidate.scores.model_dump()
        high = {key for key, value in scores.items() if value >= 2}
        if not high:
            rejected["below_threshold"] += 1
            continue
        if whitespace(candidate.original_name) not in text or (candidate.unit and whitespace(candidate.unit) not in text):
            rejected["unsupported_identity"] += 1
            continue
        if any(whitespace(e.quote) not in text for e in candidate.evidence):
            rejected["nonverbatim_evidence"] += 1
            continue
        supported = {d for e in candidate.evidence for d in e.supports}
        if not high <= supported:
            rejected["unsupported_score"] += 1
            continue
        record = candidate.model_dump()
        record["identifiers"] = [i.model_dump() for i in candidate.identifiers
                                 if whitespace(i.value).casefold() in text.casefold()
                                 and (i.kind != "doi" or re.fullmatch(r"10\.\d{4,9}/\S+", i.value))]
        # People are attached only by the explicit relationship extractor.
        record["experts"] = []
        record["teams"] = []
        if any(has_contact(e.quote) for e in candidate.evidence):
            rejected["contact_in_evidence"] += 1
            continue
        if candidate.date and candidate.date not in text:
            record["date"] = None
        if candidate.status != "unknown" and (not candidate.status_quote or whitespace(candidate.status_quote) not in text):
            record.update(status="unknown", status_quote="")
        evidence_text = " ".join(e.quote for e in candidate.evidence).casefold()
        groups = {document.organization}
        if document.organization == "ARTORG":
            groups.add("University of Bern")
        groups.update(g for g in candidate.organizations
                      if any(re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", evidence_text) for a in aliases[g]))
        record["organizations"] = [g for g in GROUPS if g in groups]
        record["evidence"] = [{**e.model_dump(), "source_url": document.url,
                                "retrieval_url": document.retrieval_url or document.url,
                                "fetched_at": document.fetched_at} for e in candidate.evidence]
        record.update(source_urls=[document.url], external_references=list(document.references)[:20],
                      source_ids=[document.source_id], fetched_at=document.fetched_at)
        # Explicit language switches identify translations of one detail page.
        # A multi-finding catalogue must never be merged by its page URL.
        if len(raw["findings"]) == 1 and whitespace(candidate.original_name) == whitespace(document.title):
            alternatives = [normalize_url(u) for u,a,*_ in document.links
                            if a.casefold() in ("english","german","deutsch","englisch","en","de")
                            and host(u) == host(document.url)
                            and len([p for p in urlsplit(u).path.split('/') if p]) >= 2]
            if alternatives:
                record["identity_urls"] = sorted(set([document.url,*alternatives]))
        # Ignore proposed tags and derive them only from validated source facts.
        record["keywords"] = record_keywords(record)
        record["source_read_version"] = SELECTION_VERSION
        score_record(record)
        accepted.append(record)
    return accepted, rejected
