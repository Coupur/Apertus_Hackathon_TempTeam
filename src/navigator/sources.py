"""Load the list of websites to crawl: UniBE subdomain inventory (xlsx) + src/sources.json."""
import json
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from . import config


@dataclass
class Source:
    id: str
    name: str
    url: str
    institution: str = "University of Bern"
    seed_paths: list[str] = field(default_factory=list)

    @property
    def host(self) -> str:
        return urlparse(self.url).netloc.lower().removeprefix("www.")

    def seeds(self) -> list[str]:
        return [self.url] + [urljoin(self.url, p) for p in self.seed_paths]


def _from_xlsx() -> list[Source]:
    import openpyxl

    wb = openpyxl.load_workbook(config.SOURCES_XLSX, read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))[1:]
    out = []
    for subdomain, description, url in rows:
        if not url:
            continue
        sid = subdomain.removesuffix(".unibe.ch").replace(".", "-")
        out.append(Source(id=sid, name=description or subdomain, url=url))
    return out


def _from_app_database() -> tuple[list[Source], set[str]]:
    if not config.APP_DB_FILE.exists():
        return [], set()

    with sqlite3.connect(f"{config.APP_DB_FILE.as_uri()}?mode=ro", uri=True) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'website_sources'"
        ).fetchone()
        if not table:
            return [], set()

        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(website_sources)").fetchall()
        }
        active_column = "is_active" if "is_active" in columns else "1"
        rows = connection.execute(
            f"""SELECT id, name, url, institution, seed_paths_json, {active_column}
               FROM website_sources ORDER BY created_at, id"""
        ).fetchall()

    database_source_ids = {row[0] for row in rows}
    sources = [
        Source(
            id=source_id,
            name=name,
            url=url,
            institution=institution,
            seed_paths=json.loads(seed_paths_json),
        )
        for source_id, name, url, institution, seed_paths_json, is_active in rows
        if is_active
    ]
    return sources, database_source_ids


def load_sources() -> list[Source]:
    by_host: dict[str, Source] = {}
    for s in _from_xlsx():
        by_host[s.host] = s
    # later files override earlier ones for the same host: discovered < xlsx < sources.json
    for path, override in ((config.DISCOVERED_SOURCES, False), (config.EXTRA_SOURCES, True)):
        if path.exists():
            for entry in json.loads(path.read_text(encoding="utf-8"))["sources"]:
                entry.pop("linked_from_pages", None)
                s = Source(**entry)
                if override or s.host not in by_host:
                    by_host[s.host] = s
    database_sources, database_source_ids = _from_app_database()
    if database_source_ids:
        by_host = {
            host: source for host, source in by_host.items() if source.id not in database_source_ids
        }
        if "unibe" in database_source_ids and not any(s.id == "unibe" for s in database_sources):
            by_host = {
                host: source
                for host, source in by_host.items()
                if host != "unibe.ch" and not host.endswith(".unibe.ch")
            }
    for source in database_sources:
        by_host[source.host] = source
    return list(by_host.values())
