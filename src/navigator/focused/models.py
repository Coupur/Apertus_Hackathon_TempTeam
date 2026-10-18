"""Strict candidate contract and bounded focused-crawl settings."""
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .keywords import MAX_KEYWORDS

GROUPS = ("University of Bern", "ARTORG", "Diabetes Center Berne")
Dimension = Literal["scientific", "practical", "capability"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Scores(StrictModel):
    scientific: int = Field(ge=0, le=4)
    practical: int = Field(ge=0, le=4)
    capability: int = Field(ge=0, le=4)


class Evidence(StrictModel):
    quote: str = Field(min_length=30, max_length=600)
    supports: list[Dimension] = Field(min_length=1, max_length=3)


class Identifier(StrictModel):
    kind: Literal["doi", "project"]
    value: str = Field(min_length=4, max_length=200)


class Expert(StrictModel):
    name: str = Field(min_length=3, max_length=150)
    role: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=200)


class Candidate(StrictModel):
    selection_method: Literal["rules"] = "rules"
    review_status: Literal["unreviewed"] = "unreviewed"
    matched_rules: list[str] = Field(default_factory=list, max_length=6)
    title: str = Field(min_length=8, max_length=250)
    original_name: str = Field(min_length=4, max_length=250)
    type: Literal["research_result", "project", "technology", "capability", "infrastructure", "achievement"]
    unit: str = Field(max_length=250)
    summary: str = Field(min_length=40, max_length=1600)
    rationale: str = Field(min_length=40, max_length=1200)
    scores: Scores
    evidence: list[Evidence] = Field(min_length=1, max_length=5)
    topics: list[str] = Field(default_factory=list, max_length=12)
    keywords: list[str] = Field(default_factory=list, max_length=MAX_KEYWORDS)
    organizations: list[Literal["University of Bern", "ARTORG", "Diabetes Center Berne"]] = Field(default_factory=list, max_length=3)
    experts: list[Expert] = Field(default_factory=list, max_length=5)
    identifiers: list[Identifier] = Field(default_factory=list, max_length=5)
    date: str | None = Field(default=None, max_length=80)
    status: Literal["active", "completed", "historical", "unknown"] = "unknown"
    status_quote: str = Field(default="", max_length=600)


@dataclass
class Document:
    url: str
    title: str
    text: str
    source_id: str
    organization: str
    fetched_at: str
    retrieval_url: str = ""
    references: tuple[str, ...] = ()


@dataclass
class Settings:
    max_fetches: int = 2000
    max_findings: int = 500
    concurrency: int = 4
    delay: float = 1.0
    max_depth: int = 8
    max_frontier: int = 10000
    max_bytes: int = 2_000_000
    source_check: bool = False
    reevaluate: bool = False
    complete: bool = False

    def __post_init__(self):
        if self.complete and self.source_check:
            raise ValueError("complete collection and source checks are separate modes")
        for key in ("max_fetches", "concurrency", "max_depth", "max_frontier", "max_bytes"):
            if getattr(self, key) < 1:
                raise ValueError(f"{key} must be positive")
        if not 1 <= self.max_findings <= 500:
            raise ValueError("max_findings must be between 1 and 500")
        if not isfinite(self.delay) or self.delay < 1.0:
            raise ValueError("delay must be finite and at least one second per domain")
