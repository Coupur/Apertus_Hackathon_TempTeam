"""Local EN/DE selection of substantive research and stronger review priorities."""
import re
from urllib.parse import urlsplit

from .models import Document, GROUPS
from .ranking import assess_evidence

RULESET_VERSION = "focused-rules-v10"


def has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def project_name(text: str) -> str | None:
    match = re.search(r"\bNCCR\s+[A-Z][A-Z0-9+-]{2,30}|(?<=[Pp]roject )[A-Z][A-Z0-9-]{3,30}\b|\b[A-Z][A-Z0-9-]{3,30}(?= [Pp]roject\b)", text)
    return match.group() if match else None


ROUTINE_TITLE = r"vacanc|job opening|position available|research assistant|newsletter|seminar|picnic|maintenance|funding applications|stellenangebot|ausschreibung|wartung"
UNSUPPORTED = (
    r"no (?:new results|clinical utility|control group|evaluation data|winners|projects|evidence)"
    r"|not (?:yet )?(?:been )?(?:demonstrated|validated|evaluated|licensed|adopted|deployed)"
    r"|applications (?:are )?(?:now )?open|work in progress|plans? to|aims? to|hopes? to"
    r"|will (?:be |become|provide|improve|reduce|validate)|could (?:improve|reduce|enable)"
    r"|did not (?:improve|reduce|demonstrate)|no (?:significant|measurable) (?:benefit|improvement|difference)"
    r"|no clinical (?:benefit|utility)|hypothes[ei][sz]|expected to|may (?:improve|reduce|provide)"
    r"|keine (?:neuen ergebnisse|kontrollgruppe|nachweise)|noch nicht (?:validiert|nachgewiesen)"
    r"|soll(?:en)? künftig|plant,|möchte"
)
TECHNOLOGY = r"platform|device|technology|method|process|protocol|hardware|robot|controller|cartridge|dataset|edition|plattform|gerät|technologie|verfahren|protokoll|datensatz"
ADOPTION = (
    r"(?:has been|was|is|were|been) (?:subsequently )?(?:adopted|licensed|incorporated|transferred)"
    r"|signed licen[cs]e agreement|used (?:in daily treatment|by \w+ (?:industrial|international))"
    r"|became the basis|wurde\w* (?:lizenziert|übernommen|integriert)|im klinischen einsatz"
)
ADOPTION_CONTEXT = r"\b(?:manufacturers?|commercial|industrial|hospitals?|daily treatment|mission|multicenter research program|university.*departments|hersteller\w*|kommerziell\w*|industrie\w*|klinisch\w*|krankenhaus\w*)\b"
DISTINCTIVE = r"validated|calibrated|standardized|reference (?:dataset|measurement)|unavailable in conventional|validiert|kalibriert|standardisiert|referenzmess|einzigartig"
ACCESS = r"external (?:research )?projects|outside research partners|external.*access|used by|adopted by|extern\w* (?:forschungs|projekt|partner)|zugang für"
COMPARATIVE = r"randomi[sz]ed|controlled study|controlled trial|kontrolliert\w* studie|randomisiert|prospective study|cross.over study|prospektiv\w* studie"
RESULT = r"improved|increased|reduced|demonstrated|established|confirmed|equivalent|comparable|verbessert|reduziert|nachgewiesen|zeigte|bestätigt"
QUANTITY = r"\b\d+(?:[.,]\d+)?\s*(?:percent|%|percentage points|patients|participants|adults|samples|eyes|prozent|patient|teilnehm|proben|augen)"
PROGRAM = r"national|multicenter|multi.center|international|national\w*|multizentrisch"
FUNDING = r"(?:CHF|EUR|USD|€|\$)\s*(\d+(?:[.,]\d+)?)\s*(?:million|mio)|(?:budget|funding|förderung)\s*(?:of|von)?\s*(\d+(?:[.,]\d+)?)\s*million"
STRATEGIC = r"European Innovation Council|Horizon Europe|European Research Council|\bNCCR\b|National\w* Forschungsschwerpunkt|National Cent(?:er|re)\w* of Competence"
CONFIRMED_ROLE = r"secured|awarded|received|selected|funded|leads?|coordinates?|leiten|koordiniert|bewilligt|erhalten"
SPECIALIZED = (
    r"organs?.on.chip|organ.chip", r"microfluidic|mikrofluid", r"3d.bioprint|3d.biodruck",
    r"bio\s*safety\s*2|\bbsl.?2\b|sicherheitsstufe.?2", r"overnight clinical|clinical facility space",
    r"soft lithograph|weichlithograph", r"gnotobiot|axeni[cs]|axenisch",
    r"next.generation.sequencing|rna.sequenc|rns.sequenz", r"confocal|konfokal",
)

# Each entry has a stable export key, dimension, type and English explanation.
RULES = {
    "comparative_result": ("scientific", "research_result", "Comparative research result",
                           "The excerpt combines a controlled study, a reported outcome and quantitative evidence."),
    "documented_adoption": ("practical", "technology", "Documented technology adoption",
                            "The excerpt combines an identifiable technology or research output with reported adoption or transfer."),
    "distinctive_capability": ("capability", "capability", "Research capability with external use",
                              "The excerpt combines a specified research capability with validation or standardization and external access or use."),
    "funded_program": ("capability", "project", "Funded collaborative research program",
                       "The excerpt describes a national or multicenter program with reported funding of at least ten million."),
    "recognized_achievement": ("scientific", "achievement", "Recognized research achievement",
                              "The excerpt combines international prize recognition with a concrete scholarly output."),
    "strategic_program": ("capability", "project", "Strategic research program",
                          "The excerpt identifies a national or competitive European research program and a confirmed institutional role or funding award."),
    "specialized_facility": ("capability", "infrastructure", "Specialized research infrastructure",
                             "The source offers a facility with at least two specific advanced laboratory or clinical capabilities."),
    "reported_research": ("scientific", "research_result", "Reported research finding",
                          "The excerpt describes a research finding or analysis with a concrete subject. Exceptional impact or clinical utility is not assumed."),
    "research_activity": ("scientific", "project", "Research project or activity",
                          "The excerpt describes research with a defined objective or method. Project aims are retained as aims, not presented as achieved results."),
    "developed_technology": ("practical", "technology", "Research technology or method",
                             "The excerpt describes a developed technology or method and its function. Commercial adoption or clinical validation is not required or inferred."),
    "research_service": ("capability", "capability", "Available research capability",
                         "The excerpt offers a specified scientific method, instrument or research service. Exceptional uniqueness or external adoption is not required."),
}
BROAD_RULES = {"reported_research", "research_activity", "developed_technology", "research_service"}
RULE_SCORES = {key: 2 if key in BROAD_RULES else 3 for key in RULES}
RESEARCH = r"\bresearch\w*|\bstud(?:y|ies)\b|scientis\w*|experiment\w*|\banalys\w*|\bsimulat\w*|\btrial\w*|forsch\w*|wissenschaft\w*|\bstudie\w*|untersuch\w*"
REPORTED = r"\b(?:found (?:that|a|an|the)|showed|shown|revealed|discovered|identified|demonstrated|confirmed|results? (?:show|suggest|indicate)|entdeckt|entdeckten|zeigte|zeigten|nachgewiesen|identifiziert)\b|zeigt,? dass|zeigen,? dass"
ACTIVITY = r"\b(?:investigate[sd]?|investigating|examine[sd]?|examining|explor(?:e[sd]?|ing)|develop(?:s|ed|ing)?|analy[sz](?:e[sd]?|ing)|characteri[sz](?:e[sd]?|ing)|understand(?:ing)?|focus(?:es)? on|stud(?:y|ies|ying) (?:how|whether|the|a)|untersucht|untersuchen|erforscht|erforschen|entwickelt|entwickeln|analysiert|analysieren)\b"
METHOD = r"sequenc\w*|genom\w*|microscop\w*|mikroskop\w*|spectroscop\w*|spektroskop\w*|imaging|bildgebung|tomograph\w*|mass spectrom\w*|massenspektrom\w*|microfluid\w*|mikrofluid\w*|\b(?:assays?|biobank\w*|bioinformat\w*|clinical\w*|klinisch\w*|tissue|gewebe\w*|sensor\w*|robot\w*|dataset\w*|datens[aä]tz\w*|simulation\w*)\b"
NO_CONTENT = r"no (?:new results|evaluation data|technical details|projects or results)|neither findings nor methods|no new (?:study result|instrument|research result)|opening hours|cafeteria|packed lunch|bibliograph\w*|literature list|publication list|publikationsliste|medienanfragen|journalist\w*|press releases?\s*[,|]|read more|mehr erfahren|\.{3}|…"
GENERIC_HEADING = r"^(?:abstract|summary|background|introduction|methods?|results?|conclusions?|objectives?|aims?|overview|description|project (?:activities|description|goals|aims|partners)|the role of science|about .+|contact\w*|funding|duration|references|publications?|literature|links?|further information|zusammenfassung|hintergrund|methoden|ergebnisse|kontakt|finanzierung|publikationen)$"
COLLECTION_TITLE = r"^(?:our )?(?:research(?: (?:activities|projects|infrastructure|areas))?|ongoing projects|current projects|all research projects|projects|news(?:.*)?|services|facilities|infrastructure|forschung(?:sprojekte)?|forschungsprojekte|projekte|aktuell\w*|archiv\w*)(?:\s*[-:|].*)?$"


def substantive_signals(quote: str) -> list[str]:
    """Require descriptive facts, not publication metadata or promotional adjectives."""
    if (len(quote) < 120 or len(quote.split()) < 18 or has(NO_CONTENT, quote)
            or not has(r"[.!?](?:\s|$)", quote)):
        return []
    matches = []
    if has(RESEARCH, quote) and has(REPORTED, quote) and not has(UNSUPPORTED, quote):
        matches.append("reported_research")
    # Research objectives qualify as projects even before results exist. The
    # clause following the action must describe more than a slogan or a list.
    action = re.search(r"(?:" + ACTIVITY + r")\s+([^.!?\n]{30,})", quote, re.I)
    if (has(RESEARCH + r"|\bprojects?\b|\bprojekt\w*", quote) and action
            and len(action.group(1).split()) >= 5
            and not has(r"work in progress|no clinical utility|no control group|clinical utility has (?:yet )?not|revised the wording|commentary|summarizes existing literature|world.leading|cutting.edge|outstanding partners", quote)):
        matches.append("research_activity")
    if (has(TECHNOLOGY, quote) and has(r"developed|designed|built|implemented|enables?|measures?|detects?|entwickelt|ermöglicht|misst|erfasst", quote)
            and has(METHOD + r"|algorithm\w*|material\w*|measurement\w*|messung\w*|data|daten\w*", quote)
            and not has(UNSUPPORTED, quote)):
        matches.append("developed_technology")
    if (has(r"\b(?:offers?|provides?|available|access|bietet|bieten|verfügbar|zugang)\b", quote)
            and has(METHOD, quote) and not has(UNSUPPORTED, quote)
            and not has(r"teaching|education|studierenden|ausbildung|our mission|mission of", quote)):
        matches.append("research_service")
    return matches


def strong_signals(quote: str) -> list[str]:
    if has(UNSUPPORTED, quote):
        return []
    matches = []
    if has(COMPARATIVE, quote) and has(RESULT, quote) and has(QUANTITY, quote):
        matches.append("comparative_result")
    if has(TECHNOLOGY, quote) and has(ADOPTION, quote) and has(ADOPTION_CONTEXT, quote):
        matches.append("documented_adoption")
    if has(r"test|assay|measurement|sample|tissue|research|messung|prüfung|forschung|proben", quote) and has(DISTINCTIVE, quote) and has(ACCESS, quote):
        matches.append("distinctive_capability")
    funding = re.search(FUNDING, quote, re.I)
    if (funding and float(next(v for v in funding.groups() if v).replace(",", ".")) >= 10
            and has(PROGRAM, quote) and has(r"program|infrastructure|initiative|programm|infrastruktur", quote)
            and has(r"funded|coordinates|led by|leads|finanziert|koordiniert|geleitet", quote)):
        matches.append("funded_program")
    if (has(r"international.*(?:grand prize|major award)|international\w*.*(?:preis|auszeichnung)", quote)
            and has(r"received|awarded|erhielt|ausgezeichnet", quote)
            and has(r"archive|edition|discovery|reconstruct|entdeckung|rekonstruktion", quote)):
        matches.append("recognized_achievement")
    if project_name(quote) and has(STRATEGIC, quote) and has(CONFIRMED_ROLE, quote):
        matches.append("strategic_program")
    if (sum(has(pattern, quote) for pattern in SPECIALIZED) >= 2
            and has(r"provides?|offers?|facility|laborator|access|services?|bietet|labor|zugang|infrastruktur", quote)):
        matches.append("specialized_facility")
    return matches


def signals(quote: str) -> list[str]:
    return strong_signals(quote) + substantive_signals(quote)


def passages(text: str):
    """Keep local context and exact whitespace-normalized quotes, never whole pages."""
    if "\n\n" in text:
        for section in text.split("\n\n"):
            yield from passages(section)
        return
    sentences = [" ".join(s.split()) for s in re.split(r"\n+|(?<=[.!?])\s+(?=[A-ZÄÖÜ])", text) if s.strip()]
    for i in range(len(sentences)):
        quote = ""
        for sentence in sentences[i:i + 8]:
            next_quote = (quote + " " + sentence).strip()
            if len(next_quote) > 600:
                break
            quote = next_quote
            # Prefer the shortest sufficient passage. An adjacent future plan
            # must not suppress an already documented result or existing service.
            if len(quote) >= 30:
                yield quote


def source_sections(document: Document):
    """Yield heading-scoped text; never assemble facts across unrelated sections."""
    parts = document.text.split("\n\n")
    for part in parts:
        heading = part.split("\n", 1)[0].strip()
        label = heading if len(parts) > 1 and 4 <= len(heading) <= 200 and not heading.endswith((".", "?", ":")) else document.title
        yield label.strip()[:250], part


def evaluate(document: Document) -> dict:
    """Extract unreviewed candidates without a model, network call or translation."""
    if has(ROUTINE_TITLE, document.title):
        return {"findings": []}
    groups = {}
    page_name = document.title
    collection = has(COLLECTION_TITLE, page_name)
    homepage = bool(re.fullmatch(r"/(?:en/|de/|index_(?:eng|ger)\.html)?", urlsplit(document.url).path))
    directory = has(r"/(?:people|staff|team|group_members|mitarbeit\w*|personen)(?:/|$)", urlsplit(document.url).path)
    for label, section in source_sections(document):
        for quote in passages(section):
            matched = signals(quote)
            event = has(r"\bworkshop|\bconference|\bsymposium|\btagung|\bveranstaltung", document.title + " " + label)
            if homepage or directory or event:
                matched = [key for key in matched if key not in BROAD_RULES]
            if not matched:
                continue
            # Detail-page subsections describe the same work. Collection pages
            # can expose several separately named projects or facilities.
            broad_only = all(key in BROAD_RULES for key in matched)
            source_name = page_name if has(GENERIC_HEADING, label) or (broad_only and not collection) else label
            name = project_name(quote) or source_name
            if len(name) < 4 or has(COLLECTION_TITLE, name) or has(r"^(?:research|projects?|(?:our )?services?|(?:recent )?news(?: archive)?|home|navigation|overview|foundation(?: landingpage.*)?|forschung|projekte|startseite)$", name):
                continue
            entry = groups.setdefault(name, {"rules": set(), "quotes": [], "section": section})
            entry["rules"].update(matched)
            supports = sorted({RULES[key][0] for key in matched})
            if not any(quote == old["quote"] for old in entry["quotes"]):
                entry["quotes"].append({"quote": quote, "supports": supports})
    findings = []
    for name, entry in list(groups.items())[:10]:
        keys = [key for key in RULES if key in entry["rules"]][:5]
        # One excerpt per rule before spare context, so every score has evidence.
        evidence = []
        quality = {q["quote"]: assess_evidence([q])["score"] for q in entry["quotes"]}
        for key in keys:
            excerpt = max((q for q in entry["quotes"] if key in signals(q["quote"])),
                          key=lambda q: (quality[q["quote"]], -len(q["quote"])))
            if excerpt not in evidence:
                evidence.append(excerpt)
        primary = keys[0]
        _, kind, label, _ = RULES[primary]
        facts = " ".join(e["quote"] for e in evidence)
        identifiers = []
        named = project_name(facts)
        if named:
            identifiers.append({"kind": "project", "value": named})
        # Only explicit labeled identifiers, never arbitrary page-wide DOIs.
        for match in re.finditer(r"(?:project (?:id|identifier)|grant (?:number|agreement)|projekt(?:nummer|kennung))\s*[:#]?\s*([A-Z0-9][A-Z0-9_-]{3,40})\b", facts, re.I):
            identifiers.append({"kind": "project", "value": match.group(1)})
        status, status_quote, date = "unknown", "", None
        for quote in passages(entry["section"]):
            if has(r"(?:project|study|experiment|program|projekt|studie).{0,60}(?:completed|concluded|abgeschlossen)|(?:completed|concluded) (?:the )?(?:project|study)", quote):
                status, status_quote = "completed", quote
                years = re.findall(r"\b(?:18|19|20)\d{2}\b", quote)
                date = years[-1] if years else None
                break
        findings.append({
            "title": f"{label} at {document.organization}", "original_name": name,
            "type": kind, "unit": "", "selection_method": "rules", "review_status": "unreviewed",
            "matched_rules": keys, "scores": {d: max((RULE_SCORES[k] for k in keys if RULES[k][0] == d), default=0)
                                               for d in ("scientific", "practical", "capability")},
            "summary": f"The source reports evidence matching the {label.lower()} rule. The original name and supporting source excerpts identify the candidate; its significance has not been manually reviewed.",
            "rationale": " ".join(RULES[k][3] for k in keys),
            "evidence": evidence, "topics": [RULES[k][2] for k in keys],
            "organizations": list(GROUPS), "identifiers": identifiers[:5], "experts": [],
            "date": date, "status": status, "status_quote": status_quote,
        })
    return {"findings": findings}
