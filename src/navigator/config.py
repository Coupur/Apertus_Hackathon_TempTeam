"""Paths, crawl limits and the Apertus endpoint. LLM_* come from the shell or src/.env."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# KEY=VALUE lines from src/.env; variables already set in the shell win
_ENV_FILE = ROOT / "src" / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _key, _sep, _value = _line.strip().partition("=")
        if _sep and not _key.startswith("#"):
            os.environ.setdefault(_key.strip(), _value.strip().strip("\"'"))

# Sources: the UniBE subdomain inventory + extra sites. Add a site by appending to src/sources.json.
SOURCES_XLSX = ROOT / "Docs" / "unibe_sous_domaines_publics_etendus.xlsx"
EXTRA_SOURCES = ROOT / "src" / "sources.json"
DISCOVERED_SOURCES = ROOT / "src" / "sources_discovered.json"

DATA_DIR = Path(os.getenv("NAVIGATOR_DATA_DIR", ROOT / "data"))
PAGES_FILE = DATA_DIR / "pages.jsonl"        # crawl:  one cleaned page per line
ENTITIES_FILE = DATA_DIR / "entities.jsonl"  # enrich: one Apertus record per page
PROFILES_FILE = DATA_DIR / "profiles.jsonl"  # index:  one profile per person / unit
VECTORS_FILE = DATA_DIR / "vectors.npy"      # index:  one embedding per profile

MAX_PAGES_PER_SOURCE = int(os.getenv("MAX_PAGES_PER_SOURCE", "100"))
CRAWL_DELAY_S = float(os.getenv("CRAWL_DELAY_S", "0.5"))
USER_AGENT = "HackApertus-ResearchNavigator/0.1 (+https://hackapertus.ch)"

# Apertus v1.5 behind any OpenAI-compatible endpoint (vLLM, SGLang, Ollama, a Swiss gateway, ...)
LLM_NAME = os.getenv("LLM_NAME", "swiss-ai/Apertus-v1.5-8B")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENABLED = bool(LLM_BASE_URL)

# Local multilingual embedding model (~470 MB, downloaded once), so search also matches across DE/EN
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")] if path.exists() else []
