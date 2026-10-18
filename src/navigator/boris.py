"""BORIS (UniBE publication repository) harvest over OAI-PMH.

Pages through ListRecords and saves every response untouched to
data/raw/boris/oai_<n>.xml. state.json holds the resumption token, so an interrupted
harvest continues where it stopped. BORIS listed 175,932 records on 2026-10-18.
"""
import json
import re
import time
from datetime import datetime, timezone

import httpx

from . import config

ENDPOINT = "https://boris-portal.unibe.ch/server/oai/request"


def harvest(max_requests: int | None = None, from_date: str | None = None, delay: float = 1.0,
            prefix: str = "oai_dc") -> dict:
    out_dir = config.RAW_DIR / "boris"
    out_dir.mkdir(parents=True, exist_ok=True)
    state_file = out_dir / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else \
        {"token": None, "requests": 0, "records": 0, "total": None, "done": False, "from": from_date}
    if state["done"]:
        print(f"  BORIS harvest already complete: {state['records']} records. Delete {state_file} to restart.")
        return state

    t0, n_this_run = time.time(), 0
    with httpx.Client(headers={"User-Agent": config.USER_AGENT}, timeout=120) as client:
        while max_requests is None or n_this_run < max_requests:
            if state["token"]:
                params = {"verb": "ListRecords", "resumptionToken": state["token"]}
            else:
                params = {"verb": "ListRecords", "metadataPrefix": prefix}
                if state.get("from"):
                    params["from"] = state["from"]
            for attempt in range(4):
                try:
                    r = client.get(ENDPOINT, params=params)
                    if r.status_code == 200:
                        break
                    print(f"  HTTP {r.status_code}, retrying")
                except httpx.HTTPError as e:
                    print(f"  {type(e).__name__}, retrying")
                time.sleep(5 * (attempt + 1))
            else:
                print("  BORIS not responding; rerun the command later to resume.")
                break

            xml = r.text
            err = re.search(r'<error code="([^"]+)"[^>]*>(.*?)</error>', xml, re.S)
            if err:
                print(f"  OAI error {err.group(1)}: {err.group(2).strip()}")
                if err.group(1) == "badResumptionToken":
                    print(f"  The token expired. Delete {state_file} to start over (saved pages are kept).")
                break

            state["requests"] += 1
            n_this_run += 1
            (out_dir / f"oai_{state['requests']:05d}.xml").write_text(xml, encoding="utf-8")
            state["records"] += xml.count("<record>")
            m = re.search(r'<resumptionToken([^>]*)>([^<]*)</resumptionToken>', xml)
            if m:
                size = re.search(r'completeListSize="(\d+)"', m.group(1))
                if size:
                    state["total"] = int(size.group(1))
            state["token"] = m.group(2).strip() if m and m.group(2).strip() else None
            state["done"] = state["token"] is None
            state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            state_file.write_text(json.dumps(state, indent=1))

            rate = n_this_run / max(time.time() - t0, 1)
            total = state["total"] or 0
            pct = f"{100 * state['records'] / total:5.1f}%" if total else "  ?  "
            eta = ""
            if total and rate:
                per_req = state["records"] / state["requests"]
                eta = f" | ETA {((total - state['records']) / per_req / rate) / 60:.0f} min"
            print(f"  BORIS {state['records']:>7}/{total or '?'} records {pct} | request {state['requests']}{eta}",
                  flush=True)
            if state["done"]:
                print("  BORIS harvest complete.")
                break
            time.sleep(delay)
    return state
