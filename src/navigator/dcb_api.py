"""Diabetes Center Berne: dump its WordPress REST API (structured JSON, no scraping needed).

Saves each response page untouched to data/raw/dcberne_api/<type>_p<page>.json.
Endpoint list checked on 2026-10-18 via https://www.dcberne.com/wp-json/.
"""
import json
import time

import httpx

from . import config

BASE = "https://www.dcberne.com/wp-json/wp/v2/"
TYPES = ["team", "project", "publication", "posts", "pages", "project_category", "publication-year", "categories"]


def dump(delay: float = 1.0) -> dict:
    out_dir = config.RAW_DIR / "dcberne_api"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=60, follow_redirects=True) as client:
        for t in TYPES:
            page, pages, n = 1, 1, 0
            while page <= pages:
                r = client.get(BASE + t, params={"per_page": 100, "page": page})
                if r.status_code != 200:
                    print(f"  {t}: HTTP {r.status_code}, skipped")
                    break
                pages = int(r.headers.get("X-WP-TotalPages", "1"))
                items = r.json()
                (out_dir / f"{t}_p{page}.json").write_text(json.dumps(items, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
                n += len(items)
                print(f"  {t:<17} page {page}/{pages}  ({n}/{r.headers.get('X-WP-Total', '?')} items)", flush=True)
                page += 1
                time.sleep(delay)
            summary[t] = n
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary
