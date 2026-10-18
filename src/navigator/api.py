"""HTTP API for the frontend.  Run: uvicorn navigator.api:app --app-dir src --port 8000"""
from fastapi import FastAPI

from . import config
from .models import CompanyRequest, SearchResponse
from .search import get_index, search

app = FastAPI(title="Research & Expertise Navigator", version="0.1")


@app.get("/health")
def health():
    return {"pages_indexed": len(get_index().docs), "llm": config.LLM_NAME if config.LLM_ENABLED else None}


@app.post("/search", response_model=SearchResponse)
def search_endpoint(req: CompanyRequest) -> SearchResponse:
    return search(req)
