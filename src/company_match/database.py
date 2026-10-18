"""Small SQLite database for companies and match results."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_DB_PATH = DATA_DIR / "companies.db"
COMPANIES_SEED = DATA_DIR / "companies.json"
EXPERTISE_SEED = DATA_DIR / "bern_expertise.json"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hq_country TEXT,
            hq_city TEXT,
            canton_bern_presence INTEGER DEFAULT 0,
            sector TEXT,
            subsector TEXT,
            description TEXT,
            keywords_json TEXT,
            needs_json TEXT,
            size TEXT,
            website TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bern_capabilities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source TEXT,
            keywords_json TEXT,
            synonyms_json TEXT,
            units_json TEXT,
            weight REAL DEFAULT 1.0
        );

        CREATE TABLE IF NOT EXISTS match_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT,
            company_name TEXT,
            match_rate REAL,
            top_capability_ids_json TEXT,
            reasons_json TEXT,
            input_payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies(sector);
        CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(name);
        """
    )
    conn.commit()


def _list_to_json(value: Any) -> str:
    if value is None:
        return "[]"
    if isinstance(value, str):
        return json.dumps([value])
    return json.dumps(list(value))


def upsert_company(conn: sqlite3.Connection, company: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO companies (
            id, name, hq_country, hq_city, canton_bern_presence, sector, subsector,
            description, keywords_json, needs_json, size, website
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            hq_country=excluded.hq_country,
            hq_city=excluded.hq_city,
            canton_bern_presence=excluded.canton_bern_presence,
            sector=excluded.sector,
            subsector=excluded.subsector,
            description=excluded.description,
            keywords_json=excluded.keywords_json,
            needs_json=excluded.needs_json,
            size=excluded.size,
            website=excluded.website
        """,
        (
            company["id"],
            company["name"],
            company.get("hq_country"),
            company.get("hq_city"),
            1 if company.get("canton_bern_presence") else 0,
            company.get("sector"),
            company.get("subsector"),
            company.get("description"),
            _list_to_json(company.get("keywords", [])),
            _list_to_json(company.get("needs", [])),
            company.get("size"),
            company.get("website"),
        ),
    )


def upsert_capability(conn: sqlite3.Connection, cap: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO bern_capabilities (
            id, name, source, keywords_json, synonyms_json, units_json, weight
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            source=excluded.source,
            keywords_json=excluded.keywords_json,
            synonyms_json=excluded.synonyms_json,
            units_json=excluded.units_json,
            weight=excluded.weight
        """,
        (
            cap["id"],
            cap["name"],
            cap.get("source"),
            _list_to_json(cap.get("keywords", [])),
            _list_to_json(cap.get("synonyms", [])),
            _list_to_json(cap.get("units", [])),
            float(cap.get("weight", 1.0)),
        ),
    )


def seed_from_json(
    conn: sqlite3.Connection,
    companies_path: Path | None = None,
    expertise_path: Path | None = None,
) -> dict[str, int]:
    companies_path = companies_path or COMPANIES_SEED
    expertise_path = expertise_path or EXPERTISE_SEED

    companies = json.loads(companies_path.read_text(encoding="utf-8"))
    expertise = json.loads(expertise_path.read_text(encoding="utf-8"))

    for company in companies:
        upsert_company(conn, company)
    for cap in expertise.get("capabilities", []):
        upsert_capability(conn, cap)

    conn.commit()
    return {"companies": len(companies), "capabilities": len(expertise.get("capabilities", []))}


def row_to_company(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "hq_country": row["hq_country"],
        "hq_city": row["hq_city"],
        "canton_bern_presence": bool(row["canton_bern_presence"]),
        "sector": row["sector"],
        "subsector": row["subsector"],
        "description": row["description"],
        "keywords": json.loads(row["keywords_json"] or "[]"),
        "needs": json.loads(row["needs_json"] or "[]"),
        "size": row["size"],
        "website": row["website"],
    }


def row_to_capability(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "source": row["source"],
        "keywords": json.loads(row["keywords_json"] or "[]"),
        "synonyms": json.loads(row["synonyms_json"] or "[]"),
        "units": json.loads(row["units_json"] or "[]"),
        "weight": float(row["weight"] or 1.0),
    }


def list_companies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM companies ORDER BY name").fetchall()
    return [row_to_company(r) for r in rows]


def get_company(conn: sqlite3.Connection, company_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM companies WHERE id = ? OR lower(name) = lower(?)",
        (company_id, company_id),
    ).fetchone()
    return row_to_company(row) if row else None


def list_capabilities(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM bern_capabilities ORDER BY name").fetchall()
    return [row_to_capability(r) for r in rows]


def save_match_run(
    conn: sqlite3.Connection,
    *,
    company_id: str | None,
    company_name: str,
    match_rate: float,
    top_capability_ids: list[str],
    reasons: list[str],
    input_payload: dict[str, Any],
) -> int:
    cur = conn.execute(
        """
        INSERT INTO match_runs (
            company_id, company_name, match_rate,
            top_capability_ids_json, reasons_json, input_payload_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            company_name,
            match_rate,
            json.dumps(top_capability_ids),
            json.dumps(reasons),
            json.dumps(input_payload),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def init_db(db_path: Path | str | None = None, seed: bool = True) -> sqlite3.Connection:
    conn = connect(db_path)
    init_schema(conn)
    if seed:
        seed_from_json(conn)
    return conn
