"""Web UI + HTTP API.  Run from src/:  uvicorn navigator.api:app --port 8000  ->  http://localhost:8000"""
import sqlite3

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

from . import config, index
from .clusters import cluster_findings, latest_clusters
from .llm import InvalidModelResponse, LLMUnavailable
from .models import CompanyRequest, SearchResponse
from .search import search

app = FastAPI(title="Research & Expertise Navigator API", version="0.3")


class ClusterRunRequest(BaseModel):
    batch_size: int = Field(default=50, ge=1, le=80)


@app.get("/health")
def health():
    return {"profiles_indexed": len(index.load()[0]), "llm": config.LLM_NAME if config.LLM_ENABLED else None}


@app.post("/search", response_model=SearchResponse)
def search_endpoint(req: CompanyRequest) -> SearchResponse:
    return search(req)


@app.post("/search/legacy", response_model=SearchResponse)
def legacy_search_endpoint(req: CompanyRequest) -> SearchResponse:
    from .legacy_search import search as legacy_search
    return legacy_search(req)


@app.get("/clusters")
def clusters_endpoint() -> dict:
    result = latest_clusters()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No cluster results found. Run `python -m navigator cluster` after focused-crawl.",
        )
    return result


@app.post("/clusters/run")
def run_clusters_endpoint(request: ClusterRunRequest) -> dict:
    try:
        return cluster_findings(batch_size=request.batch_size)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LLMUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except InvalidModelResponse as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except ValidationError as error:
        raise HTTPException(status_code=502, detail="Apertus response did not match the required schema") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Apertus endpoint request failed") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except sqlite3.Error as error:
        raise HTTPException(status_code=500, detail="Could not persist the cluster result") from error
