"""Steps 3 + 4: profile -> what the company needs from Bern -> retrieval queries for each need.

Each need belongs to one resource section (prompts.SECTIONS) and carries the question the company
would ask. Its queries are written like a sentence on a Bern research page, in English and German,
because the index matches page-like text better than questions.
"""
import re
from concurrent.futures import ThreadPoolExecutor

from .. import config, llm
from .lexicon import TOPICS, Topic
from .ties import name_terms
from .prompts import (NEEDS_SYSTEM, QUERIES_SYSTEM, QUESTION_FIX_SYSTEM, SECTIONS, need_text, profile_text,
                      sections_text)

TOPIC_BY_KEY = {t.key: t for t in TOPICS}
QUESTION_SHAPE = re.compile(r"\s*(who|which|what)\b", re.I)  # what a university website can answer
OFFERED = [k for k in SECTIONS]  # all of A-M; news (N) is not something a company needs

# Templates for the no-LLM path. {topic} reads like "drug delivery devices and diabetes care".
RULES = {
    "A": ("Contact with researchers who are experts in {topic}.",
          "Who in Bern researches {topic}?",
          ["professor and research group leader working on {en1}", "researchers with expertise in {en2}"],
          ["Professorin oder Professor und Forschungsgruppe für {de1}"]),
    "B": ("Institutes, groups or clinics in Bern that work on {topic}.",
          "Which Bern institutes and research groups work on {topic}?",
          ["institute and research group for {en1}"], ["Institut und Forschungsgruppe für {de1}"]),
    "C": ("Know-how in the methods and technologies we build on: {tech}.",
          "Which Bern groups work with {tech}?",
          ["research on {en_all}", "{summary}"], ["Forschung zu {de_all}"]),
    "D": ("Research projects in Bern that resemble our problems in {topic}.",
          "Which Bern research projects deal with {topic}?",
          ["research project on {en1} with industry partners"], ["Forschungsprojekt zu {de1} mit Industriepartnern"]),
    "E": ("Labs, instruments or facilities for {topic}, such as {infra}.",
          "Which Bern core facilities are open to external users for {topic}?",
          ["{infra} available to external users", "core facility and equipment for {en2}"],
          ["Infrastruktur und Geräte für {de1}"]),
    "F": ("Services for companies in {topic}, such as {services}.",
          "Which Bern units offer {services} to companies?",
          ["{services} for industry partners in {en1}"], ["Dienstleistungen für Unternehmen im Bereich {de1}"]),
    "G": ("A way to collaborate on or license research in {topic}.",
          "Which University of Bern office handles technology transfer and licensing with companies?",
          ["technology transfer, licensing and industry collaboration in {en1}"],
          ["Technologietransfer und Industriekooperation im Bereich {de1}"]),
    "H": ("Evidence that Bern groups publish strong work in {topic}.",
          "Which Bern groups publish on {topic}?",
          ["publications and journal articles on {en1}"], ["Publikationen zu {de1}"]),
    "I": ("Funding for a joint innovation project in {topic}.",
          "Which funding instruments support joint innovation projects of companies with Bern researchers?",
          ["Innosuisse innovation project with an implementation partner in {en1}"],
          ["Innosuisse Innovationsprojekt mit Umsetzungspartner im Bereich {de1}"]),
    "J": ("Guidance on the rules for {reg}.",
          "Which Bern units advise on regulatory requirements for {reg}?",
          ["regulatory requirements and approval of {reg}", "ethics committee and regulatory affairs for {reg}"],
          ["Zulassung und regulatorische Anforderungen für {reg_de}"]),
    "K": ("Partners in the Bern ecosystem active in {topic}.",
          "Which companies already partner with University of Bern research in {topic}?",
          ["cooperation with hospitals, companies and networks in {en1}"],
          ["Zusammenarbeit mit Spital, Industrie und Netzwerken im Bereich {de1}"]),
    "L": ("Support for setting up a site in the Canton of Bern.",
          "Which offices support companies setting up a site in the Canton of Bern?",
          ["support for companies settling in the Canton of Bern"],
          ["Unterstützung für Firmenansiedlung im Kanton Bern"]),
    "M": ("Graduates to hire and training for our staff in {topic}.",
          "Which Bern study programmes and continuing education courses teach {topic}?",
          ["study programme and continuing education in {en1}"], ["Studiengang und Weiterbildung in {de1}"]),
}


def _clean(xs, n: int, min_words: int = 1) -> list[str]:
    out = []
    for x in xs or []:
        s = re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", str(x)).strip().strip('"').strip()
        if len(s.split()) >= min_words and s.lower() not in (o.lower() for o in out):
            out.append(s)
    return out[:n]


def _section(raw) -> str | None:
    m = re.match(r"\s*([A-M])\b", str(raw or "").upper())
    return m.group(1) if m else None


# ---------- rules ----------

def _words(profile: dict) -> dict:
    topics = [TOPIC_BY_KEY[t["key"]] for t in profile.get("topics", [])]
    summary = re.sub(r"\s+", " ", profile.get("summary") or profile["name"]).strip()[:200]
    if profile.get("kind") != "idea":  # the company's name only adds noise to a query over Bern pages
        for brand in (profile["name"], profile["name"].split()[0]):
            if len(brand) > 2:
                summary = re.sub(rf"\b{re.escape(brand)}\w*\s*", "", summary).strip(" ,.-–&") or summary
    if not topics:
        return {"topics": [], "topic": profile.get("sector") or summary, "tech": profile.get("sector") or summary,
                "en1": summary, "en2": summary, "en_all": summary, "de1": "", "de_all": "", "summary": summary,
                "infra": "", "services": "", "reg": "", "reg_de": ""}
    hits = [t["hits"] for t in profile["topics"]]
    lead = topics[0]
    second = topics[1] if len(topics) > 1 else None
    close = second is not None and hits[1] >= 0.5 * hits[0]  # name two topics only when both are strong
    first_of = lambda attr: [getattr(t, attr)[0] for t in topics[:3] if getattr(t, attr)]
    reg = next((t.reg for t in topics if t.reg), None)
    return {
        "topics": topics,
        "topic": f"{lead.label}, {second.label}" if close else lead.label,
        "tech": ", ".join(t["value"] for t in profile.get("technologies", [])[:3]) or lead.label,
        "en1": " and ".join(lead.en[:2]),
        "en2": " and ".join((second.en[:2] if second else lead.en[1:3]) or lead.en[:1]),
        "en_all": ", ".join(first_of("en")),
        "de1": " und ".join(lead.de[:2]),
        "de_all": ", ".join(first_of("de")),
        "summary": summary,
        "infra": ", ".join(list(dict.fromkeys(i for t in topics for i in t.infra))[:3]),
        "services": " or ".join(list(dict.fromkeys(s for t in topics for s in t.services))[:2]),
        "reg": reg[0] if reg else "",
        "reg_de": reg[1] if reg else "",
    }


def _rules_sections(profile: dict, w: dict) -> list[str]:
    secs = ["A", "B", "C", "D"]
    if w["infra"]:
        secs.append("E")
    if w["services"]:
        secs.append("F")
    secs.append("G")
    if profile.get("stage") in ("startup", "sme", "unknown"):
        secs.append("I")
    if w["reg"]:
        secs.append("J")
    secs.append("K")
    if profile.get("in_bern") is not True:
        secs.append("L")
    if profile.get("hiring"):
        secs.append("M")
    return secs


def _evidence(profile: dict, section: str) -> tuple[str, str]:
    """(basis, evidence): a stated goal, want or challenge if one fits the section, else the main topic."""
    fits = {"M": ("wants",), "I": ("wants", "goals"), "G": ("wants",), "K": ("wants",), "L": ("goals",),
            "D": ("challenges", "goals"), "C": ("technologies",)}
    for field in fits.get(section, ()):
        for item in profile.get(field, []):
            if section != "M" or re.search(r"hir|talent|career|karriere|stellen|join", item["value"], re.I):
                return ("stated" if field != "technologies" else "inferred"), item["value"]
    tech = profile.get("technologies") or [{"value": profile.get("sector") or profile.get("summary", "")}]
    return "inferred", tech[0]["value"]


def _fill(templates: list[str], w: dict) -> list[str]:
    out = []
    for t in templates:
        keys = re.findall(r"{(\w+)}", t)
        if all(w.get(k) for k in keys):
            out.append(t.format(**w))
    return out


def _rule_need(profile: dict, w: dict, sec: str) -> dict:
    need, question, en, de = RULES[sec]
    basis, evidence = _evidence(profile, sec)
    keywords = list(dict.fromkeys(term for t in w["topics"][:2] for term in t.en + t.de))[:12]
    en_q, de_q = _fill(en, w), _fill(de, w)
    return {"section": sec, "need": need.format(**w), "question": question.format(**w), "basis": basis,
            "evidence": evidence, "en": [q for q in en_q if not _german(q)],
            "de": [q for q in en_q if _german(q)] + de_q, "keywords": keywords, "generated_by": "rules"}


def rules_needs(profile: dict) -> list[dict]:
    w = _words(profile)
    return [_rule_need(profile, w, sec) for sec in _rules_sections(profile, w)]


# ---------- Apertus ----------

QUERY_QUESTION = re.compile(r"^\s*(which|who|what|how|where|when|why|is|are|can|could|do|does|welche\w*|wer|was"
                            r"|wie|wo|gibt es|kann|können)\b", re.I)
# every page in the index is in Bern: the place only adds noise to a query (keeps "Diabetes Center Berne")
PLACE_SUBS = [(re.compile(p, re.I), r) for p, r in [
    (r"\b(at|in|from|of|by|with|an|von|aus|mit|bei)\s+(the\s+|der\s+)?(University of Bern|Universit[äa]t Bern|Uni Bern"
     r"|UniBE)\b", ""),
    (r"\b(Universit[äa]t Bern|Uni Bern)\b", "Universität"),
    (r"\b(University of Bern|UniBE)('s)?\b", "university"),
    (r"\b(in|at|from|with|aus|mit|bei|von|im Raum)\s+Bern\b", ""),
    (r"\bBern(er|ese|'s)?\b\s*", ""),
]]


def _page_like(q: str, names: list[str]) -> str | None:
    """A query as page text: questions are dropped, places and the company's own name removed."""
    if "?" in q or QUERY_QUESTION.match(q):
        return None
    for rx, rep in PLACE_SUBS:
        q = rx.sub(rep, q)
    for name in names:
        q = re.sub(rf"\b((with|from|at|by|of|for|mit|von|bei|für)\s+)?{re.escape(name)}\w*", "", q, flags=re.I)
    q = re.sub(r"\s{2,}", " ", q).strip(" ,.;:-")
    return q if len(q.split()) >= 4 else None


def _llm_queries(profile: dict, need: dict) -> dict:
    out = llm.chat_json(QUERIES_SYSTEM, need_text(profile, need), max_tokens=700, temperature=0.2)
    names = name_terms(profile)
    page_like = lambda xs, n: _clean([q for q in (_page_like(str(x), names) for x in xs or []) if q], n, 3)
    return {"en": page_like(out.get("en"), 4), "de": page_like(out.get("de"), 3),
            "keywords": _clean(out.get("keywords"), 14)}


def llm_needs(profile: dict, max_needs: int, trace: list[str]) -> list[dict]:
    user = profile_text(profile) + "\n\nResource sections:\n" + sections_text(OFFERED)
    out = llm.chat_json(NEEDS_SYSTEM.format(max_needs=max_needs), user, max_tokens=1800)
    needs = []
    for n in out.get("needs") or []:
        if not isinstance(n, dict):
            continue
        sec = _section(n.get("section"))
        need, question = str(n.get("need", "")).strip(), str(n.get("question", "")).strip()
        if not sec or not need:
            trace.append(f"needs: skipped malformed item {str(n)[:120]}")
            continue
        basis = str(n.get("basis", "")).strip().lower()
        needs.append({"section": sec, "need": need, "question": question or need,
                      "basis": basis if basis in ("stated", "inferred") else "inferred",
                      "evidence": str(n.get("evidence", "")).strip(), "generated_by": f"apertus:{config.LLM_NAME}"})
    needs = needs[:max_needs]
    if not needs:
        raise ValueError("no usable needs in the reply")

    def fix_question(n):
        """One rewrite for a question a website cannot answer ("Can we...", "How can we...")."""
        if QUESTION_SHAPE.match(n["question"]):
            return
        try:
            reply = llm.chat(QUESTION_FIX_SYSTEM, n["question"], max_tokens=150)
            new = next((l for l in reply.splitlines() if l.strip()), "").strip().strip('"“”').strip()
        except Exception as e:
            trace.append(f"question fix failed ({e}): {n['question'][:100]}")
            return
        if QUESTION_SHAPE.match(new):
            trace.append(f"question rewritten: {n['question'][:100]} -> {new[:100]}")
            n["question_original"], n["question"] = n["question"], new
        else:
            trace.append(f"question still not who/which/what after rewrite: {new[:100]}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fix_question, needs))  # before the queries, which are written from the question

    w = _words(profile)

    def queries(n):
        try:
            q = _llm_queries(profile, n)
            if q["en"]:
                return q
            trace.append(f"queries for {n['section']}: empty reply, using templates")
        except Exception as e:
            trace.append(f"queries for {n['section']} failed ({e}); using templates")
        fb = _rule_need(profile, w, n["section"])
        return {"en": fb["en"] or [n["need"]], "de": fb["de"], "keywords": fb["keywords"]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, q in zip(needs, pool.map(queries, needs)):
            n.update(q)
    return needs


def build_needs(profile: dict, max_needs: int, trace: list[str]) -> list[dict]:
    needs = None
    if config.LLM_ENABLED:
        try:
            needs = llm_needs(profile, max_needs, trace)
        except Exception as e:
            trace.append(f"needs LLM failed ({e}); using rules")
    if needs is None:
        needs = rules_needs(profile)
    for i, n in enumerate(needs, 1):
        s = SECTIONS[n["section"]]
        n["id"] = f"n{i}"
        n["section_name"], n["finds"], n["coverage"] = s["name"], s["finds"], s["coverage"]
    return needs


GERMAN = re.compile(r"\b(und|der|die|das|für|mit|von|zur|zum|im|bietet|sich|ist|eine?[nrs]?|auf|bei)\b", re.I)


def _german(text: str) -> bool:
    return len(GERMAN.findall(text)) >= 2


def to_queries(needs: list[dict]) -> list[dict]:
    """Flat query list in the shape `navigator retrieve` reads (qid, text, from), plus what it is for.
    A query's language is read from its text, since a company's own sentences may be German."""
    qs = []
    for n in needs:
        count = {"en": 0, "de": 0}
        for listed in ("en", "de"):
            for text in n.get(listed, []):
                lang = "de" if listed == "de" or _german(text) else "en"
                count[lang] += 1
                qs.append({"qid": f"{n['id']}.{lang}{count[lang]}", "text": text, "lang": lang, "need_id": n["id"],
                           "section": n["section"], "finds": n["finds"], "from": f"need {n['id']} ({n['section']})"})
    return qs
