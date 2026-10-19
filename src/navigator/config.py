"""Paths, crawl limits and the Apertus endpoint. LLM_* come from the shell or src/.env."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False, interpolate=False, encoding="utf-8-sig")
load_dotenv(ROOT / "src" / ".env", override=False, interpolate=False, encoding="utf-8-sig")
DATA_DIR = Path(os.getenv("NAVIGATOR_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
SOURCES_XLSX = ROOT / "Docs" / "unibe_sous_domaines_publics_etendus.xlsx"
EXTRA_SOURCES = ROOT / "src" / "sources.json"
DISCOVERED_SOURCES = ROOT / "src" / "sources_discovered.json"

PAGES_FILE = DATA_DIR / "pages.jsonl"        # crawl:  one cleaned page per line
ENTITIES_FILE = DATA_DIR / "entities.jsonl"  # enrich: one Apertus record per page
PROFILES_FILE = DATA_DIR / "profiles.jsonl"  # index:  one profile per person / unit
VECTORS_FILE = DATA_DIR / "vectors.npy"      # index:  one embedding per profile

MAX_PAGES_PER_SOURCE = int(os.getenv("MAX_PAGES_PER_SOURCE", "100"))
CRAWL_DELAY_S = float(os.getenv("CRAWL_DELAY_S", "0.5"))
CRAWL_CONCURRENCY = int(os.getenv("CRAWL_CONCURRENCY", "8"))
USER_AGENT = "HackApertus-ResearchNavigator/0.1 (+https://hackapertus.ch)"

# Apertus v1.5 behind any OpenAI-compatible endpoint (vLLM, SGLang, Ollama, a Swiss gateway, ...)
LLM_NAME = os.getenv("LLM_NAME", "swiss-ai/Apertus-v1.5-8B")
REPORT_LLM_NAME = os.getenv("REPORT_LLM_NAME", LLM_NAME)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENABLED = bool(LLM_BASE_URL)

# Local multilingual embedding model (~470 MB, downloaded once), so search also matches across DE/EN
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")] if path.exists() else []
