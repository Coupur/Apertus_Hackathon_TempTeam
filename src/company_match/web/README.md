# Company Layer UI (React)

Simple interface for the Bern **life-science company layer**:

1. Paste text / upload PDF / enter website  
2. See extracted main info + keywords (early / mid / late)  
3. See priority rating and teammate handoff queries  

## Run the unified UI

From the repository root, install the shared workspace dependencies:

```bash
npm install
```

Start the two Python APIs in separate terminals:

```bash
PYTHONPATH=src uvicorn company_match.api:app --app-dir src --reload --port 8088
PYTHONPATH=src uvicorn navigator.api:app --reload --port 8000
```

Start the unified React interface from the repository root:

```bash
npm run dev
```

Open http://localhost:5173. Use the top navigation to switch between company
matching and research themes. Vite proxies `/api` to the company API and
`/navigator-api` to the Navigator API. Set `NAVIGATOR_API_URL` before starting
Vite to use a Navigator API on another host.
