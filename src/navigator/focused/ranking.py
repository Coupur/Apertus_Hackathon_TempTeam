"""Explainable evidence signals, not probabilities or verified scientific impact.

Only retained source excerpts are scored. Missing signals mean unknown, not poor
research. Each criterion takes its strongest asserted sentence; repetition,
institution names, page dates and promotional adjectives earn no points.
"""
import re
from collections import Counter

RANKING_VERSION = "evidence-v1"
SELECTION_VERSION = "unified-v1"
WEIGHTS = {"methodology": 20, "quantitative": 20, "validation": 20,
           "adoption": 15, "accessibility": 10, "collaboration": 10,
           "reproducibility": 5}


def has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


FUTURE = r"\b(?:will|would|could|might|may|plans?|planned|planning|aims?|hopes?|expected|proposed|hypothetical|claims?|allegedly|soll\w*|geplant\w*|künftig|beabsichtigt\w*)\b"
NEGATED = r"\b(?:no|not|never|without|lack\w*|failed|unvalidated|unconfirmed|unreplicated|unavailable|kein\w*|nicht|ohne|fehlt\w*)\b"
METHOD = r"sequenc\w*|microscop\w*|mikroskop\w*|spectroscop\w*|spektroskop\w*|tomograph\w*|mass spectrom\w*|interviews?|simulation\w*|microfluid\w*|mikrofluid\w*|\bassays?\b|archival analysis|textual analysis|quellenkrit\w*"
SAMPLE = r"\b\d[\d, .]*\s*(?:participants?|patients?|samples?|specimens?|subjects?|documents?|records?|studies|patient\w*|teilnehm\w*|proben|dokument\w*)\b"
MEASURE = r"\b\d+(?:[.,]\d+)?\s*(?:%|percent\w*|prozent\w*|percentage points|picoseconds?|milliseconds?|micrometers?|nanometers?|mmhg|mg/dl)"
OUTCOME = r"improved|increased|reduced|achieved|measured|accuracy|sensitivity|specificity|agreement|recovery rate|maintain\w*|error|verbessert\w*|reduziert\w*|gemessen\w*|genauigkeit|übereinstimmung"
PUBLIC = r"openly (?:released|available|accessible)|publicly (?:released|available|accessible)|open.access|open.source|frei zugänglich|öffentlich verfügbar"
RESOURCE = r"\b(?:datasets?|data|source code|code|protocols?|critical edition|datens[aä]tz\w*|quellcode|protokoll\w*)\b"


def sentence_scores(text: str) -> dict[str, tuple[int, str]]:
    """Score a single assertion so unrelated excerpts cannot complete a rule."""
    scores = {}

    def award(key, score, reason):
        if score > scores.get(key, (0, ""))[0]:
            scores[key] = (score, reason)

    if has(FUTURE, text):
        return scores
    # A completed negative study can still report its design and sample size.
    guard = re.sub(r"no significant (?:difference|benefit|effect)|keinen signifikanten (?:unterschied|effekt)", "", text, flags=re.I)
    if has(NEGATED, guard):
        return scores
    if has(METHOD, text):
        award("methodology", 1, "A specific research method is described.")
    if has(r"prospective|retrospective|longitudinal|cohort|case.control|cross.sectional|systematic review|paired (?:study|comparison)|prospektiv\w*|kohorten\w*|längsschnitt\w*|systematisch\w* übersicht", text):
        award("methodology", 2, "An explicit study design is reported.")
    controlled = has(r"controlled (?:study|trial|experiment)|control group|kontrolliert\w* (?:studie|versuch)|kontrollgruppe", text)
    randomized = (has(r"\brandomi[sz]ed\b|\brandomisiert\w*", text)
                  and not has(r"\bnon[ -]?randomi[sz]ed\b", text))
    if controlled or randomized or has(r"blinded (?:study|evaluation)|verblindet\w* studie", text):
        award("methodology", 3, "A comparative, randomized or blinded design is reported.")
    if randomized and (controlled or has(r"double.blind|doppelblind", text)):
        award("methodology", 4, "Randomization and a control or double blinding are reported together.")

    sample = has(SAMPLE, text)
    measured = has(MEASURE, text) and has(OUTCOME, text)
    if sample:
        award("quantitative", 1, "A numerical sample or corpus size is reported.")
    if measured:
        award("quantitative", 2, "A numerical measurement or outcome is reported.")
        if sample or has(r"\bp\s*[<=>]\s*0[.,]\d+", text):
            award("quantitative", 3, "A numerical outcome includes sample size or a statistical test.")
        if has(r"(?:confidence interval|\bCI\b|konfidenzintervall)\s*[:=(]?\s*\[?[-+]?\d", text):
            award("quantitative", 4, "A numerical outcome includes a numerical confidence interval.")

    if has(r"\b(?:validated|calibrated|standardized|validiert\w*|kalibriert\w*|standardisiert\w*)\b", text):
        award("validation", 1, "Validation, calibration or standardization is stated.")
        if has(r"against|compared (?:with|to)|reference (?:method|measurement)|gold standard|benchmark|gegen|referenzmess\w*", text):
            award("validation", 2, "Validation names a reference or comparison.")
    if has(r"independent (?:testing|validation|evaluation)|externally validated|unabhängig\w* (?:prüfung|validierung)|extern validiert", text):
        award("validation", 3, "Independent testing or external validation is explicitly reported.")
    if has(r"independently replicat\w*|replicated by independent|independently reproduced|unabhängig repliziert\w*|unabhängig reproduziert\w*", text):
        award("validation", 4, "Independent replication is explicitly reported.")

    if has(r"(?:tested|evaluated|demonstrated) (?:a |the )?prototype|prototype (?:was |has been )?tested|prototyp\w*.*getestet", text):
        award("adoption", 1, "A tested prototype is reported.")
    if has(r"pilot (?:deployment|line|plant)|deployed in (?:a |the )?pilot|pilotbetrieb|pilotanlage", text):
        award("adoption", 2, "Pilot operation or deployment is reported.")
    deployed = has(r"(?:was|were|is|has been) (?:adopted|licensed|deployed)|signed licen[cs]e agreement|used in daily|im klinischen einsatz|wurde\w* (?:lizenziert|übernommen)|became the basis", text)
    if deployed and has(r"manufactur\w*|commercial|industr\w*|hospital\w*|clinical|mission|research program|universit\w*|hersteller\w*|klinisch\w*", text):
        award("adoption", 3, "External adoption, licensing or operational use is reported.")
        if has(r"\b\d+\s+(?:hospitals?|manufacturers?|companies|institutions?|departments?|kliniken|hersteller\w*)\b", text):
            award("adoption", 4, "Operational adoption includes a numerical count of external users.")

    if has(r"offers?|provides?|available|bietet|verfügbar", text) and has(METHOD + r"|facility|instrument|research service|labor|forschungsdienst", text):
        award("accessibility", 1, "A specific research service or facility is offered.")
    if has(r"external.*access|access.*external|outside research partners|external (?:research )?projects|zugang für externe|externe forschungspartner", text):
        award("accessibility", 2, "Access for external researchers is stated.")
    if has(r"(?:access|booking|application|request) (?:process|procedure|form)|apply for access|zugang.*antrag|buchungsformular", text):
        award("accessibility", 3, "A concrete access or application procedure is described.")
    if has(PUBLIC, text) and has(RESOURCE, text):
        award("accessibility", 3, "An openly accessible research output is reported.")
        if has(r"download|repository|github\.com|zenodo|license|licence|herunterlad\w*|lizenz", text):
            award("accessibility", 4, "An open research output has a distribution or licensing route.")

    if has(r"collaborat\w*|joint research|forschungskooperation|zusammenarbeit", text):
        award("collaboration", 1, "Research collaboration is described.")
    if has(r"multicent(?:er|re)|multi.cent(?:er|re)|multizentrisch\w*|\b(?:[2-9]|\d{2,}) (?:institutions|centers|centres|universities|institutionen|zentren)\b", text):
        award("collaboration", 2, "Multiple research sites or institutions are explicitly involved.")
    if has(r"national\w* (?:research )?(?:program\w*|initiative|consortium)|national\w* forschungsprogramm", text):
        award("collaboration", 3, "A national research program or consortium is described.")
    if has(r"international\w* (?:research )?(?:collaborat\w*|consortium|program\w*)", text) and has(r"\b(?:[2-9]|\d{2,}) (?:countries|ländern|länder)\b", text):
        award("collaboration", 4, "International research collaboration names its multi-country scale.")

    if has(r"documented (?:method|protocol)|published (?:method|protocol)|dokumentiert\w* (?:methode|protokoll)|veröffentlicht\w* protokoll", text):
        award("reproducibility", 1, "A documented or published method/protocol is reported.")
    if has(PUBLIC, text) and has(RESOURCE, text):
        award("reproducibility", 2, "Public research data, code, protocols or a critical edition are reported.")
        if has(r"dataset|\bdata\b|datensatz|daten", text) and has(r"\bcode\b|protocol|quellcode|protokoll", text):
            award("reproducibility", 3, "Public data and code or protocols are reported together.")
        if has(r"10\.\d{4,9}/\S+|github\.com/\S+|\bversion\s+\d", text):
            award("reproducibility", 4, "A public research output has an explicit persistent identifier, repository or version.")
    return scores


def assess_evidence(evidence: list[dict]) -> dict:
    criteria = {key: {"score": 0, "reason": "No qualifying assertion in retained evidence.",
                      "quote": "", "source_url": ""} for key in WEIGHTS}
    for item in evidence:
        quote = " ".join(item["quote"].split())
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])", quote):
            for key, (score, reason) in sentence_scores(sentence).items():
                previous = criteria[key]
                # Stable choice of the shortest equally strong supporting assertion.
                if score > previous["score"] or (score == previous["score"] and
                        (len(sentence), sentence, item.get("source_url", "")) <
                        (len(previous["quote"]), previous["quote"], previous["source_url"])):
                    criteria[key] = {"score": score, "reason": reason, "quote": sentence,
                                     "source_url": item.get("source_url", "")}
    return {"version": RANKING_VERSION,
            "score": sum(WEIGHTS[k] * value["score"] for k, value in criteria.items()) / 4,
            "criteria": criteria}


def evaluation_for(record: dict) -> dict:
    if record.get("type") in ("expert", "team"):
        from .entities import assess_entity
        return assess_entity(record)
    return assess_evidence(record.get("evidence", []))


def score_record(record: dict) -> dict:
    record["evaluation"] = evaluation_for(record)
    # Only a newly validated source read creates the new contract fields.
    if record.get("source_read_version") == SELECTION_VERSION:
        record.update(selection_score=record["evaluation"]["score"], selection_version=SELECTION_VERSION)
    return record


def rank(record: dict) -> tuple:
    score = record.get("selection_score")
    if score is None:
        score = evaluation_for(record)["score"]
    return score, record.get("id", "")


def ranking_summary(records: list[dict]) -> dict:
    evaluations = [r.get("evaluation") or evaluation_for(r) for r in records]
    groups = Counter(rank(record)[:-1] for record in records)
    n = len(records)
    from .entities import ENTITY_WEIGHTS, ENTITY_VERSION
    by_type = {}
    for kind in sorted({r.get('type', 'unknown') for r in records}):
        subset = [e for r, e in zip(records, evaluations) if r.get('type', 'unknown') == kind]
        histogram = Counter(e['score'] for e in subset)
        by_type[kind] = {'records': len(subset), 'distinct_scores': len(histogram),
                         'min_score': min(histogram), 'max_score': max(histogram),
                         'modal_score_fraction': max(histogram.values()) / len(subset),
                         'score_distribution': dict(sorted(histogram.items())),
                         'criterion_coverage': {
                             key: sum(e['criteria'].get(key, {}).get('score', 0) > 0 for e in subset) / len(subset)
                             for key in sorted({k for e in subset for k in e['criteria']})}}
    return {"version": SELECTION_VERSION, "weights": {"work": WEIGHTS, "entity": ENTITY_WEIGHTS}, "records": n,
            "scoring_versions": {"work": RANKING_VERSION, "entity": ENTITY_VERSION}, "by_type": by_type,
            "mean_score": round(sum(e["score"] for e in evaluations) / n, 2) if n else None,
            "distinct_rank_groups": len(groups),
            "tied_record_fraction": sum(size for size in groups.values() if size > 1) / n if n else None,
            "criterion_coverage": {key: sum(e["criteria"].get(key, {}).get("score", 0) > 0 for e in evaluations) / n
                                   if n else None for key in {*WEIGHTS, *ENTITY_WEIGHTS}}}
