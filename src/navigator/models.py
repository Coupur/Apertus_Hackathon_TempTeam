"""API contract. Step 1 = CompanyRequest (input), step 3 = SearchResponse (output).

The input format is still open in the team — only `need` is required, so the frontend can
start with a single free-text box and add structured fields later without breaking anything.
"""
from pydantic import BaseModel, Field


class CompanyRequest(BaseModel):
    need: str = Field(..., description="What the company is looking for, in its own words (any language).",
                      examples=["We build wearable glucose sensors and need a partner for clinical validation"])
    company_name: str | None = None
    sector: str | None = Field(None, examples=["MedTech"])
    keywords: list[str] = Field(default_factory=list, examples=[["CGM", "biosensor"]])
    looking_for: list[str] = Field(default_factory=list, description="e.g. expert, infrastructure, project, service",
                                   examples=[["expert", "infrastructure"]])
    max_results: int = Field(10, ge=1, le=30)


class Person(BaseModel):
    name: str
    role: str = ""
    email: str = ""
    expertise: list[str] = []
    source_url: str


class Match(BaseModel):
    unit: str
    institution: str
    people: list[Person] = []
    expertise: list[str] = []
    projects: list[str] = []
    infrastructure: list[str] = []
    reason: str = Field(..., description="Why this unit matches the company need")
    sources: list[str] = Field(..., description="Public pages that support this result")
    score: float


class SearchResponse(BaseModel):
    request: CompanyRequest
    interpreted_need: str
    search_terms: list[str]
    results: list[Match]
    no_reliable_match: bool = False
    note: str = ""
