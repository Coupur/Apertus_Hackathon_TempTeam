# Company Layer UI (React)

Simple interface for the Bern **life-science company layer**:

1. Paste text / upload PDF / enter website  
2. See extracted main info + keywords (early / mid / late)  
3. See priority rating and teammate handoff queries  

## Run

Terminal 1 — API:

```bash
cd /path/to/repo
source .venv/bin/activate   # or: python3 -m venv .venv && source .venv/bin/activate
pip install -r src/company_match/requirements.txt
export PYTHONPATH=src
uvicorn company_match.api:app --app-dir src --reload --port 8088
```

Terminal 2 — UI:

```bash
cd src/company_match/web
npm install
npm run dev
```

Open http://localhost:5173

The Vite dev server proxies `/api` → `http://127.0.0.1:8088`.
