"""Central configuration: paths, crawl limits and LLM endpoint (from env vars)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """KEY=value lines from the repo's .env (gitignored, see .env.example). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("NAVIGATOR_DATA_DIR", ROOT / "data"))
APP_DB_FILE = ROOT / ".data" / "auth.sqlite"
SOURCES_XLSX = ROOT / "Docs" / "unibe_sous_domaines_publics_etendus.xlsx"
EXTRA_SOURCES = ROOT / "src" / "sources.json"
DISCOVERED_SOURCES = ROOT / "src" / "sources_discovered.json"  # written by `navigator discover`

RAW_DIR = DATA_DIR / "raw"                   # untouched downloads: raw/<source_id>/, raw/boris/, raw/dcberne_api/
PAGES_FILE = DATA_DIR / "pages.jsonl"        # cleaned text extracted from raw HTML
ENTITIES_FILE = DATA_DIR / "entities.jsonl"  # LLM-enriched structured records

# Crawl settings
MAX_PAGES_PER_SOURCE = int(os.getenv("MAX_PAGES_PER_SOURCE", "100"))
CRAWL_DELAY_S = float(os.getenv("CRAWL_DELAY_S", "1.0"))
CRAWL_CONCURRENCY = int(os.getenv("CRAWL_CONCURRENCY", "4"))  # sites crawled in parallel
USER_AGENT = "HackApertus-ResearchNavigator/0.1 (+https://hackapertus.ch)"

# LLM (Apertus v1.5 via any OpenAI-compatible endpoint: vLLM, SGLang, Ollama, ...)
LLM_NAME = os.getenv("LLM_NAME", "swiss-ai/Apertus-v1.5-8B")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENABLED = bool(LLM_BASE_URL)
