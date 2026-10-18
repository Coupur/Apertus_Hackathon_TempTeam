"""Web UI + HTTP API.  Run from src/:  uvicorn navigator.api:app --port 8000  ->  http://localhost:8000"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import config, index
from .models import CompanyRequest, SearchResponse
from .search import search

app = FastAPI(title="Research & Expertise Navigator", version="0.2")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health")
def health():
    return {"profiles_indexed": len(index.load()[0]), "llm": config.LLM_NAME if config.LLM_ENABLED else None}


@app.post("/search", response_model=SearchResponse)
def search_endpoint(req: CompanyRequest) -> SearchResponse:
    return search(req)
