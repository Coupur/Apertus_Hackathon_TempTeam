"""LLM medical-profile extraction with evidence verification.

Pipeline
--------
source text ──► clean + de-duplicate ──► LLM (Apertus first, prompts in profile_prompts.py)
            ──► parse JSON (one repair retry) ──► verify every evidence quote against the source
            ──► drop unsupported items ──► sanity checks (summary ≠ what_they_do, length, gaps)

Only items whose quote is actually found in the source survive, so the profile
stays traceable even if the model hallucinates.

Results are cached on disk (``data/llm_cache/``) by source hash + prompt version,
so demo re-runs are instant and deterministic.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .kimi_summary import llm_chat, llm_configured
from .profile_prompts import (
    BACKGROUND_HQ_SYSTEM,
    BACKGROUND_HQ_USER,
    BUSINESS_MODELS,
    LITE_PROMPT_VERSION,
    build_lite_messages,
    NEED_LABELS,
    PROMPT_VERSION,
    REPAIR_PROMPT,
    build_messages,
)

CACHE_DIR = Path(__file__).resolve().parent / "data" / "llm_cache"
MAX_SOURCE_CHARS = 9000
LIST_FIELDS = (
    "therapeutic_areas",
    "indications",
    "modalities_technologies",
    "products_platforms",
    "patient_populations",
    "development_activities",
)

_MARKETING_RE = re.compile(
    r"(?i)\b(for more than \d+ years|since \d{4}|our purpose|one purpose|our mission|"
    r"we believe|join (us|our)|redefine the future|award[- ]winning|world[- ]class|"
    r"cookie|privacy policy|all rights reserved|subscribe|newsletter|follow us)\b"
)

# Text in a web page that addresses an AI model rather than a human reader
INJECTION_RE = re.compile(
    r"(?i)(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard .{0,30}instructions|"
    r"system prompt|you are (an?|the) (ai|assistant|language model|chatbot)|as an ai\b|"
    r"\b(assistant|llm|chatgpt|model)\s*[:,]|new instructions|respond (only )?with|"
    r"output the following|say (that )?\w+ (needs|is|has))"
)

_STOP = set(
    """a an the and or of for to in on with by from as at is are be been this that these those
    its their our we they it which who whose into across within over under via per plus more
    company companies develops developing developed manufacturing manufactures provides providing
    offers offering focused focus based including include includes such other new also than
    people patients products product solutions technologies technology platform platforms""".split()
)


# ---------------------------------------------------------------------------
# Source preparation
# ---------------------------------------------------------------------------

def strip_injections(text: str) -> tuple[str, int]:
    """Remove sentences that try to instruct the model (prompt injection in web pages)."""
    removed = 0
    kept: list[str] = []
    for line in (text or "").splitlines():
        parts = re.split(r"(?<=[.!?])\s+", line)
        good = [p for p in parts if not INJECTION_RE.search(p)]
        removed += len(parts) - len(good)
        kept.append(" ".join(good))
    return "\n".join(kept), removed


def build_corpus(text: str, meta_description: str = "") -> str:
    """De-duplicate paragraphs, push marketing lines to the end, cap length."""
    text, _ = strip_injections(text)
    meta_description, _ = strip_injections(meta_description)
    seen: set[str] = set()
    medical: list[str] = []
    marketing: list[str] = []
    for block in re.split(r"\n\s*\n|\n", "\n".join([meta_description or "", text or ""])):
        para = re.sub(r"\s+", " ", block).strip()
        if len(para) < 25:
            continue
        key = re.sub(r"[^a-z0-9]", "", para.lower())[:160]
        if key in seen or any(key in s for s in seen if len(key) > 40):
            continue
        seen.add(key)
        (marketing if _MARKETING_RE.search(para) else medical).append(para)
    corpus = "\n".join(medical + marketing)
    return corpus[:MAX_SOURCE_CHARS]


# ---------------------------------------------------------------------------
# Evidence verification
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[–—‐-]", "-", s)
    s = re.sub(r"[^\w\s'%/+-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_supported(quote: str, source_norm: str, threshold: float = 0.85) -> bool:
    """Exact (normalised) substring, or a near-verbatim match (≥85 % contiguous)."""
    q = _norm(quote)
    if len(q) < 6:
        return False
    if q in source_norm:
        return True
    m = SequenceMatcher(None, source_norm, q, autojunk=False).find_longest_match(
        0, len(source_norm), 0, len(q)
    )
    return m.size / max(len(q), 1) >= threshold


def _ground_parentheticals(term: str, source_norm: str) -> str:
    """Drop "(…)" additions the source doesn't contain, e.g. "Kisqali (ribociclib)" → "Kisqali".

    Keeps standard abbreviations of the term itself, e.g. "continuous glucose monitoring (CGM)".
    """
    def keep(m: re.Match) -> str:
        inner = m.group(1).strip()
        n = _norm(inner)
        if n and (n in source_norm or (inner.isupper() and len(inner) <= 6)):
            return m.group(0)
        return ""

    return re.sub(r"\s*\(([^()]{1,60})\)", keep, term).strip()


def _content_words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9-]{3,}", (s or "").lower()) if w not in _STOP}


def _grounding_ratio(sentence: str, source_norm: str, supported_terms: list[str]) -> float:
    """Share of content words in a generated sentence that the source/verified items support."""
    words = _content_words(sentence)
    if not words:
        return 1.0
    allowed = set(re.findall(r"[a-z][a-z0-9-]{3,}", source_norm))
    for t in supported_terms:
        allowed |= _content_words(t)
    ok = sum(1 for w in words if w in allowed or any(w[:6] == a[:6] for a in allowed if len(a) >= 6))
    return ok / len(words)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_json(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    c = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    try:
        data = json.loads(c)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", c, flags=re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _clip(s: Any, max_words: int) -> str:
    words = re.sub(r"\s+", " ", str(s or "")).strip().split(" ")
    out = " ".join(words[:max_words]).strip()
    if len(words) > max_words:
        out = out.rstrip(",;:") + "…"
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NEED_INTENT = re.compile(
    r"(?i)\b(seek\w*|looking for|look for|search\w* for|need\w*|require\w*|want\w*|"
    r"interested in|open to|plan\w* to|aim\w* to|partner\w*|collaborat\w*|invite\w*|wish\w*)\b"
)


def validate_profile(data: dict[str, Any], source: str) -> tuple[dict[str, Any], list[str]]:
    """Keep only evidence-backed items; return (clean_profile, warnings)."""
    src = _norm(source)
    warnings: list[str] = []
    dropped: list[str] = []
    out: dict[str, Any] = {}

    for field in LIST_FIELDS:
        items = []
        for it in data.get(field) or []:
            if isinstance(it, str):
                it = {"term": it, "evidence": ""}
            if not isinstance(it, dict):
                continue
            term = _ground_parentheticals(_clip(it.get("term"), 12), src)
            ev = str(it.get("evidence") or "").strip()
            if not term:
                continue
            if quote_supported(ev, src):
                if term.lower() not in {x["term"].lower() for x in items}:
                    items.append({"term": term, "evidence": ev})
            else:
                dropped.append(f"{field}: {term}")
        out[field] = items[:10]

    # Business model (enum + evidence)
    bm = data.get("business_model") or {}
    if isinstance(bm, str):
        bm = {"value": bm, "evidence": ""}
    bm_val = str(bm.get("value") or "").strip()
    match = next((b for b in BUSINESS_MODELS if b.lower().split(" (")[0] in bm_val.lower()), None)
    if match and quote_supported(str(bm.get("evidence") or ""), src):
        out["business_model"] = {"value": match, "evidence": bm.get("evidence")}
    else:
        out["business_model"] = None
        if bm_val:
            dropped.append(f"business_model: {bm_val}")

    # Needs: allowed labels + must be evidenced
    needs = []
    for it in data.get("partnership_needs") or []:
        if not isinstance(it, dict):
            continue
        label = next(
            (n for n in NEED_LABELS if n.lower() == str(it.get("need") or "").strip().lower()), None
        )
        ev_need = str(it.get("evidence") or "")
        if (
            label
            and quote_supported(ev_need, src)
            and _NEED_INTENT.search(ev_need)
            and not INJECTION_RE.search(ev_need)
        ):
            if label not in [n["need"] for n in needs]:
                needs.append({"need": label, "evidence": it.get("evidence")})
        elif it.get("need"):
            dropped.append(f"need: {it.get('need')}")
    out["partnership_needs"] = needs

    # Headquarters / sites: only with a verifiable quote (footer/imprint text included)
    hq = data.get("headquarters") or {}
    if isinstance(hq, dict) and (hq.get("city") or hq.get("country")) and quote_supported(
        str(hq.get("evidence") or ""), src
    ):
        out["headquarters"] = {
            "city": _clip(hq.get("city"), 4) or None,
            "country": _clip(hq.get("country"), 4) or None,
            "evidence": hq.get("evidence"),
        }
    else:
        out["headquarters"] = None
        if isinstance(hq, dict) and (hq.get("city") or hq.get("country")):
            dropped.append(f"headquarters: {hq.get('city') or ''} {hq.get('country') or ''}".strip())
    sites = []
    for it in data.get("sites") or []:
        if isinstance(it, dict) and it.get("place") and quote_supported(str(it.get("evidence") or ""), src):
            sites.append({"place": _clip(it["place"], 5), "type": _clip(it.get("type"), 5),
                          "evidence": it.get("evidence")})
    out["sites"] = sites[:8]

    supported_terms = [x["term"] for f in LIST_FIELDS for x in out[f]]
    if out["business_model"]:
        supported_terms.append(out["business_model"]["value"])

    # Keywords: keep only those grounded in source or in verified items
    kws = []
    for kw in data.get("medical_keywords") or []:
        k = str(kw).strip().lower()
        if not k or k in kws:
            continue
        if _norm(k) in src or any(k in t.lower() or t.lower() in k for t in supported_terms):
            kws.append(k)
    out["medical_keywords"] = kws[:15]

    # Sentences
    what = _clip(data.get("what_they_do"), 40)
    summary = _clip(data.get("summary"), 90)
    suff = str(data.get("information_sufficiency") or "").lower()
    if suff not in {"sufficient", "limited", "insufficient"}:
        suff = "limited"
    if not supported_terms and suff == "sufficient":
        suff = "insufficient"

    for name, sent in (("what_they_do", what), ("summary", summary)):
        ratio = _grounding_ratio(sent, src, supported_terms)
        if sent and ratio < 0.6:
            warnings.append(
                f"{name} contains wording not supported by the source "
                f"(grounding {ratio:.0%}); rebuilt from verified items."
            )
            if name == "what_they_do":
                what = ""
            else:
                summary = ""

    if what and summary and SequenceMatcher(None, what.lower(), summary.lower()).ratio() > 0.8:
        summary = ""  # duplicate of what_they_do → rebuild below

    out["what_they_do"] = what or compose_what_they_do(data.get("company_name"), out)
    out["summary"] = summary or compose_summary(out, suff)
    out["information_sufficiency"] = suff
    out["missing_information"] = [
        _clip(m, 15) for m in (data.get("missing_information") or []) if str(m).strip()
    ][:6]
    out["company_name"] = data.get("company_name")
    out["dropped_unsupported"] = dropped
    if dropped:
        warnings.append(f"Dropped {len(dropped)} LLM item(s) without verifiable source quote.")
    return out, warnings


def _terms(profile: dict[str, Any], field: str, n: int = 4) -> list[str]:
    return [x["term"] for x in profile.get(field) or []][:n]


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def compose_what_they_do(name: Any, p: dict[str, Any]) -> str:
    bm = (p.get("business_model") or {}).get("value") or "Life-science company"
    bm = bm.split(" (")[0]
    mods = _terms(p, "modalities_technologies") or _terms(p, "products_platforms")
    areas = _terms(p, "indications") or _terms(p, "therapeutic_areas")
    if not (mods or areas):
        return f"{bm[:1].upper()}{bm[1:]}; the source does not specify products or therapeutic areas."
    s = f"{bm[:1].upper()}{bm[1:]}"
    if mods:
        s += f" working on {_join(mods)}"
    if areas:
        s += f" in {_join(areas)}"
    return s + "."


def compose_summary(p: dict[str, Any], sufficiency: str) -> str:
    parts = []
    areas = _terms(p, "therapeutic_areas", 5)
    ind = _terms(p, "indications", 5)
    pops = _terms(p, "patient_populations", 3)
    dev = _terms(p, "development_activities", 3)
    if areas:
        parts.append(f"Therapeutic areas named in the source: {_join(areas)}.")
    if ind:
        parts.append(f"Indications: {_join(ind)}.")
    if pops:
        parts.append(f"Patient populations: {_join(pops)}.")
    if dev:
        parts.append(f"Development / clinical activity: {_join(dev)}.")
    if not parts:
        return (
            "The source contains no concrete medical information (no therapeutic areas, products "
            "or indications) — only brand/marketing text. Provide an About, Pipeline or Products page."
        )
    if sufficiency != "sufficient":
        parts.append("Source detail is limited.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _cache_path(corpus: str) -> Path:
    h = hashlib.sha256(f"{PROMPT_VERSION}\n{corpus}".encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{h}.json"


def extract_medical_profile(
    text: str,
    *,
    meta_description: str = "",
    extra_text: str = "",
    source_type: str = "text",
    source_ref: str = "",
    name_hint: str | None = None,
    use_cache: bool = True,
    lite: bool = False,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (profile, warnings). profile is None when no LLM / call failed."""
    if not llm_configured():
        return None, ["LLM profile skipped: set LLM_NAME / LLM_BASE_URL / LLM_API_KEY (Apertus)."]
    corpus = build_corpus(text, meta_description)
    # Lite: short input — on local 7B models prompt processing dominates the latency
    max_chars = int(os.getenv("LLM_LITE_MAX_CHARS") or "2000") if lite else MAX_SOURCE_CHARS
    if extra_text:
        # Footer / imprint (addresses) — appended in its own labelled block
        footer, _ = strip_injections(extra_text)
        foot = footer[: 400 if lite else 1500]
        corpus = corpus[: max_chars - len(foot) - 30] + "\n[Footer / imprint]\n" + foot
    else:
        corpus = corpus[:max_chars]
    if len(corpus) < 40:
        return None, [
            "LLM profile skipped: source too short. "
            "Paste a company blurb/URL/PDF, or a company name so web search can fill context."
        ]

    cache = _cache_path(("lite\n" if lite else "") + corpus)
    raw: dict[str, Any] | None = None
    model = ""
    if use_cache and cache.is_file():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            raw, model = cached.get("raw"), cached.get("model", "")
        except (OSError, json.JSONDecodeError):
            raw = None

    warnings: list[str] = []
    if raw is None:
        if lite:
            messages = build_lite_messages(corpus, name_hint=name_hint)
        else:
            messages = build_messages(
                corpus, source_type=source_type, source_ref=source_ref, name_hint=name_hint
            )
        # Keep tokens modest — local 7B models are much faster on shorter JSON.
        content, model, w = llm_chat(
            messages,
            max_tokens=int(os.getenv("LLM_LITE_MAX_TOKENS") or "300") if lite else 700,
            json_mode=True,
            timeout=float(os.getenv("OLLAMA_PROFILE_TIMEOUT_S") or "120"),
        )
        warnings.extend(w)
        raw = _parse_json(content)
        from . import budget

        # One repair retry only if there is clearly time for it
        if raw is None and content and budget.has(30):
            content2, model, w2 = llm_chat(
                [*messages, {"role": "assistant", "content": content[:4000]},
                 {"role": "user", "content": REPAIR_PROMPT}],
                max_tokens=700,
                json_mode=True,
                timeout=float(os.getenv("OLLAMA_PROFILE_TIMEOUT_S") or "120"),
            )
            warnings.extend(w2)
            raw = _parse_json(content2)
        if raw is None:
            warnings.append("LLM profile: no valid JSON returned; using rule-based fields.")
            return None, warnings
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"model": model, "raw": raw}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    profile, vwarn = validate_profile(raw, corpus)
    profile["model"] = model
    profile["prompt_version"] = LITE_PROMPT_VERSION if lite else PROMPT_VERSION
    return profile, [*warnings, *vwarn]


def llm_background_hq(name: str, website: str | None) -> dict[str, Any] | None:
    """Last-resort HQ from model knowledge. Caller MUST flag it unverified."""
    if not llm_configured() or os.getenv("LLM_BACKGROUND_FACTS", "1").strip().lower() in {"0", "false", "off", "no"}:
        return None
    key = f"bg-hq\n{PROMPT_VERSION}\n{name}\n{website}"
    cache = CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8")) or None
        except (OSError, json.JSONDecodeError):
            pass
    content, _, _ = llm_chat(
        [
            {"role": "system", "content": BACKGROUND_HQ_SYSTEM},
            {"role": "user", "content": BACKGROUND_HQ_USER.format(name=name, website=website or "unknown")},
        ],
        max_tokens=80,
        temperature=0.0,
    )
    data = _parse_json(content) or {}
    result = None
    if str(data.get("confidence") or "").lower() == "high" and (data.get("city") or data.get("country")):
        result = {"city": data.get("city"), "country": data.get("country")}
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
    return result
