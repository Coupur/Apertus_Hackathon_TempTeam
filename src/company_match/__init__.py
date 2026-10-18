"""Company matching layer for Bern Research & Expertise Navigator."""

# Load repo-root .env before any module reads LLM_* (translation runs before the
# summary layer, so lazy loading there left Apertus unused on the first document).
from .kimi_summary import _load_dotenv as _load_env

_load_env()

from .engine import CompanyMatchEngine, CompanyMatchResult, match_company
from .layer import (
    auto_search_companies,
    export_for_teammate,
    ingest_company_sources,
    match_company_information,
    teammate_match_queue,
)

try:
    from .vectorstore import get_qdrant_store, index_ingest_batch
except Exception:  # optional dependency
    get_qdrant_store = None  # type: ignore
    index_ingest_batch = None  # type: ignore

__all__ = [
    "CompanyMatchEngine",
    "CompanyMatchResult",
    "match_company",
    "match_company_information",
    "auto_search_companies",
    "ingest_company_sources",
    "teammate_match_queue",
    "export_for_teammate",
    "get_qdrant_store",
    "index_ingest_batch",
]
