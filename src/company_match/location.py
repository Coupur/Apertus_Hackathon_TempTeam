"""Headquarters / Swiss presence resolution with provenance.

Resolution order (first hit wins for HQ; every hit is recorded in ``hq_source``):

1. ``source``          labelled line in the source ("Headquarters: Zurich, Switzerland")
2. ``json_ld``         schema.org Organization address on the website
3. ``llm_quote``       LLM medical profile, backed by a verbatim quote from the source
4. ``footer/imprint``  postal address in the page footer or imprint / contact page
5. ``wikidata``        public structured record (P159 HQ, P17 country), matched by website
                       domain or exact name — always stored with its Wikidata URL
6. ``llm_knowledge``   model background knowledge — LAST resort, flagged *unverified*,
                       never used for Bern presence or scoring

Bern presence (scoring input) only comes from 1–5, i.e. verifiable sources.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

# Canton of Bern municipalities that commonly host life-science sites
BERN_CANTON_PLACES = {
    "bern", "berne", "burgdorf", "biel", "bienne", "biel/bienne", "thun", "langenthal",
    "köniz", "koniz", "muri bei bern", "ittigen", "ostermundigen", "worb", "münsingen",
    "munsingen", "lyss", "interlaken", "spiez", "liebefeld", "zollikofen", "belp",
    "moosseedorf", "ins", "kirchberg", "huttwil", "langnau", "bolligen", "gümligen", "gumligen",
}

SWISS_CITIES = {
    "zurich", "zürich", "basel", "geneva", "genève", "geneve", "lausanne", "lucerne", "luzern",
    "zug", "st. gallen", "st gallen", "lugano", "winterthur", "schlieren", "allschwil",
    "neuchâtel", "neuchatel", "fribourg", "aarau", "baar", "visp", "stein", "kaiseraugst",
    "rotkreuz", "cham", "schaffhausen", "chur", "sion", "solothurn", "olten", "monthey",
    "nyon", "plan-les-ouates", "epalinges", "kloten", "dübendorf", "dubendorf",
} | BERN_CANTON_PLACES

COUNTRIES = [
    "Switzerland", "Germany", "France", "Italy", "Austria", "Liechtenstein", "Netherlands",
    "Belgium", "Luxembourg", "Denmark", "Sweden", "Norway", "Finland", "Ireland",
    "United Kingdom", "UK", "Spain", "Portugal", "Poland", "Czech Republic", "Israel",
    "United States", "USA", "Canada", "Japan", "China", "South Korea", "Korea", "India",
    "Singapore", "Australia", "Brazil",
]
_COUNTRY_ALIASES = {
    "schweiz": "Switzerland", "suisse": "Switzerland", "svizzera": "Switzerland",
    "ch": "Switzerland", "deutschland": "Germany", "usa": "United States",
    "u.s.a.": "United States", "us": "United States", "uk": "United Kingdom",
}

# "CH-4056 Basel" / "4056 Basel" / "3008 Bern"
SWISS_POSTAL_RE = re.compile(
    r"\b(?:CH[-\s]?)?([1-9]\d{3})\s+([A-ZÄÖÜ][a-zäöüéèàç]+(?:[ -/][A-ZÄÖÜa-zäöüéèàç]+)?)"
)
COUNTRY_RE = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in sorted(COUNTRIES, key=len, reverse=True))
    + r"|Schweiz|Suisse|Svizzera)\b"
)
TLD_COUNTRY = {".ch": "Switzerland", ".de": "Germany", ".fr": "France", ".it": "Italy",
               ".at": "Austria", ".jp": "Japan", ".nl": "Netherlands", ".dk": "Denmark"}


def normalize_country(c: str | None) -> str | None:
    if not c:
        return None
    c = c.strip().strip(".")
    return _COUNTRY_ALIASES.get(c.lower(), c)


def in_canton_bern(city: str | None) -> bool:
    return bool(city) and city.strip().lower() in BERN_CANTON_PLACES


def find_postal_address(text: str) -> tuple[str | None, str | None, str | None]:
    """Find a postal-address style HQ in footer / imprint text → (city, country, evidence)."""
    if not text:
        return None, None, None
    for line in re.split(r"[\n|·•]", text):
        line = re.sub(r"\s+", " ", line).strip()
        if not (8 <= len(line) <= 240):
            continue
        m = SWISS_POSTAL_RE.search(line)
        if m and m.group(2).lower() in SWISS_CITIES:
            cm = COUNTRY_RE.search(line)
            country = normalize_country(cm.group(1)) if cm else "Switzerland"
            return m.group(2), country, line
    # Non-Swiss: "<City>, <Country>" on an address-like line
    for line in re.split(r"[\n|·•]", text):
        line = re.sub(r"\s+", " ", line).strip()
        cm = COUNTRY_RE.search(line)
        if not cm or len(line) > 200:
            continue
        if not re.search(r"\d", line):  # require a street number / postcode
            continue
        before = line[: cm.start()].rstrip(" ,")
        # Walk comma segments backwards: skip postcodes / state codes ("MA 02139"), take the city
        for seg in reversed([x.strip() for x in before.split(",") if x.strip()][-3:]):
            seg = re.sub(r"^\d{4,6}\s+|\s+\d{4,6}$", "", seg).strip()
            if re.fullmatch(r"[A-Z]{2}(?:\s+\d+)?", seg) or re.search(r"\d", seg):
                continue
            if re.fullmatch(r"[A-Z][A-Za-zäöüéèàç .'-]{2,30}", seg):
                return seg, normalize_country(cm.group(1)), line
    return None, None, None


# ---------------------------------------------------------------------------
# Wikidata (public, structured, citable)
# ---------------------------------------------------------------------------

_UA = "BernCompanyMatch/0.4 (hackathon research prototype)"
_COMPANY_HINTS = (
    "company", "corporation", "manufacturer", "pharmaceutical", "biotechnology",
    "medical", "multinational", "enterprise", "business", "firm", "conglomerate",
)


def _get_json(url: str, timeout: float = 5.0) -> Any:
    from . import budget

    if not budget.has(2):
        raise TimeoutError("time budget used up")
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=budget.clamp(timeout)) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _domain(url: str | None) -> str:
    if not url:
        return ""
    host = urllib.parse.urlparse(url if "//" in url else f"//{url}").netloc.lower()
    return host.removeprefix("www.")


def _claim_ids(entity: dict[str, Any], prop: str) -> list[str]:
    out = []
    for c in (entity.get("claims") or {}).get(prop) or []:
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
        elif isinstance(v, str):
            out.append(v)
    return out


def wikidata_enabled() -> bool:
    return os.getenv("WIKIDATA_LOOKUP", "1").strip().lower() not in {"0", "false", "off", "no"}


def lookup_wikidata(name: str, website: str | None = None, *, fetch=_get_json) -> dict[str, Any] | None:
    """Return {hq_city, hq_country, wikidata_id, wikidata_url, matched_by} or None.

    Accepts an entity only if its official website (P856) matches the source domain,
    or (no website given) its label equals the name and the description is company-like.
    """
    if not name or not wikidata_enabled():
        return None
    try:
        q = urllib.parse.quote(name)
        search = fetch(
            "https://www.wikidata.org/w/api.php?action=wbsearchentities"
            f"&search={q}&language=en&type=item&limit=7&format=json"
        )
        cands = [c for c in (search or {}).get("search") or [] if c.get("id")]
        if not cands:
            return None
        ids = "|".join(c["id"] for c in cands)
        ents = (
            fetch(
                "https://www.wikidata.org/w/api.php?action=wbgetentities"
                f"&ids={ids}&props=claims|labels|descriptions&languages=en&format=json"
            )
            or {}
        ).get("entities") or {}
    except Exception:
        return None

    src_dom = _domain(website)
    chosen, matched_by = None, None
    for c in cands:
        ent = ents.get(c["id"]) or {}
        sites = [_domain(u) for u in _claim_ids(ent, "P856")]
        if src_dom and any(s and (s == src_dom or src_dom.endswith("." + s) or s.endswith("." + src_dom)) for s in sites):
            chosen, matched_by = ent, f"official website {src_dom}"
            break
    if chosen is None and not src_dom:
        for c in cands:
            ent = ents.get(c["id"]) or {}
            label = ((ent.get("labels") or {}).get("en") or {}).get("value", "")
            desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value", "").lower()
            if label.lower() == name.lower() and any(h in desc for h in _COMPANY_HINTS):
                chosen, matched_by = ent, "exact name + company description"
                break
    if chosen is None:
        return None

    hq_ids = _claim_ids(chosen, "P159")
    country_ids = _claim_ids(chosen, "P17")
    label_ids = [i for i in [*hq_ids[:1], *country_ids[:1]] if i]
    labels: dict[str, str] = {}
    if label_ids:
        try:
            lab = fetch(
                "https://www.wikidata.org/w/api.php?action=wbgetentities"
                f"&ids={'|'.join(label_ids)}&props=labels&languages=en&format=json"
            )
            for k, v in ((lab or {}).get("entities") or {}).items():
                labels[k] = ((v.get("labels") or {}).get("en") or {}).get("value", "")
        except Exception:
            pass
    city = labels.get(hq_ids[0]) if hq_ids else None
    country = labels.get(country_ids[0]) if country_ids else None
    if not (city or country):
        return None
    qid = chosen.get("id") or next((k for k, v in ents.items() if v is chosen), "")
    return {
        "hq_city": city,
        "hq_country": country,
        "wikidata_id": qid,
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
        "matched_by": matched_by,
    }


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

def resolve_location(
    *,
    name: str | None,
    website: str | None,
    rule_city: str | None,
    rule_country: str | None,
    rule_evidence: str | None,
    json_ld: dict[str, Any] | None,
    profile: dict[str, Any] | None,
    footer_text: str = "",
    legal_text: str = "",
    legal_url: str | None = None,
    llm_background=None,
    wikidata_lookup=None,
) -> dict[str, Any]:
    """Return {hq_city, hq_country, hq_source:{method, evidence, url, verified}, bern_sites:[...]}."""
    def out(city, country, method, evidence=None, url=None, verified=True):
        return {
            "hq_city": city,
            "hq_country": normalize_country(country),
            "hq_source": {"method": method, "evidence": evidence, "url": url, "verified": verified},
        }

    result: dict[str, Any] | None = None
    if rule_city or rule_country:
        result = out(rule_city, rule_country, "source", rule_evidence)
    elif json_ld and (json_ld.get("hq_city") or json_ld.get("hq_country")):
        c = json_ld.get("hq_country")
        if isinstance(c, dict):
            c = c.get("name")
        result = out(json_ld.get("hq_city"), c, "json_ld", "schema.org address", website)
    elif ((profile or {}).get("headquarters") or {}).get("city") or (
        ((profile or {}).get("headquarters") or {}).get("country")
    ):
        hq = profile["headquarters"]
        result = out(hq.get("city"), hq.get("country"), "llm_quote", hq.get("evidence"), website)
    else:
        for text, method, url in ((footer_text, "footer", website), (legal_text, "imprint", legal_url)):
            city, country, ev = find_postal_address(text)
            if city or country:
                result = out(city, country, method, ev, url)
                break
    if result is None and name:
        wd = (wikidata_lookup or lookup_wikidata)(name, website)
        if wd:
            result = out(
                wd["hq_city"], wd["hq_country"], "wikidata",
                f"Wikidata {wd['wikidata_id']} (matched by {wd['matched_by']})", wd["wikidata_url"],
            )
    if result is None and llm_background is not None and name:
        bg = llm_background(name, website)
        if bg and (bg.get("city") or bg.get("country")):
            result = out(
                bg.get("city"), bg.get("country"), "llm_knowledge",
                "Model background knowledge — not found in any source; verify before use.",
                None, verified=False,
            )
    if result is None:
        tld = next((c for t, c in TLD_COUNTRY.items() if _domain(website).endswith(t)), None)
        result = out(None, tld, "domain_hint" if tld else "none",
                     f"country-code domain ({_domain(website)})" if tld else None, None, verified=False)

    # Bern sites: verified quotes only (source / LLM-quoted sites / HQ itself)
    sites = []
    if result["hq_source"]["verified"] and in_canton_bern(result["hq_city"]):
        sites.append({"place": result["hq_city"], "type": "headquarters",
                      "evidence": result["hq_source"]["evidence"], "url": result["hq_source"]["url"]})
    for s in (profile or {}).get("sites") or []:
        if in_canton_bern(s.get("place")):
            sites.append({**s, "url": website})
    result["bern_sites"] = sites
    return result
