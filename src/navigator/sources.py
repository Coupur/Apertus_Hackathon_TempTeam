"""Load the list of websites to crawl: UniBE subdomain inventory (xlsx) + src/sources.json."""
import json
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


def load_sources() -> list[Source]:
    by_host: dict[str, Source] = {}
    for s in _from_xlsx():
        by_host[s.host] = s
    if config.EXTRA_SOURCES.exists():
        for entry in json.loads(config.EXTRA_SOURCES.read_text(encoding="utf-8"))["sources"]:
            s = Source(**entry)
            by_host[s.host] = s  # sources.json overrides the xlsx entry for the same host
    return list(by_host.values())
