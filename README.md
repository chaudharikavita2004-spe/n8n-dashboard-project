# Auto Dashboard Project — Python Backend Edition

A fully automated pipeline: add/update data in Google Sheets → n8n (with a
Python code node) pre-cleans it → a Python FastAPI backend does the heavy
cleaning with pandas, stores it, and serves a live JSON API → a dashboard
renders it automatically.

---

## Technologies Used

| Layer | Technology | Role |
|---|---|---|
| **Data intake** | Google Sheets | Where you paste/upload raw data (`Raw Data` tab) |
| **Automation / orchestration** | [n8n](https://n8n.io) | Watches the sheet, triggers on new rows, runs the pipeline |
| **Automation logic (light clean)** | **Python**, via n8n's built-in Code node (Pyodide sandbox, standard library only) | Trims whitespace, drops empty rows before sending to the backend |
| **Backend / API** | **Python 3 + FastAPI** | Receives rows via HTTP, does the real cleaning, stores data, serves the dashboard API |
| **Data cleaning (heavy)** | **pandas** (inside the backend) | Type coercion, date normalization, blank-fill, deduplication |
| **Storage** | **SQLite** (via Python's built-in `sqlite3`) | Local database file (`backend/dashboard.db`), zero setup |
| **Transport (n8n → backend)** | HTTP (n8n's HTTP Request node → FastAPI `POST /api/ingest`) | JSON over REST, no Google publish step needed |
| **Transport (backend → dashboard)** | HTTP (dashboard's `fetch()` → FastAPI `GET /api/dashboard`) | Live JSON, always current |
| **Dashboard front end** | Plain HTML, CSS, JavaScript (single file, no build step) | Fetches the backend's JSON and renders the UI |
| **Charts** | [Chart.js v4](https://www.chartjs.org/) (via CDN) | Bar, doughnut, and line charts |
| **Browser storage** | `localStorage` | Remembers your backend URL and refresh interval |

This replaces the earlier "publish Google Sheet as CSV" approach: now
**Python does all the cleaning and aggregation**, and the dashboard talks
to a real backend API instead of parsing a spreadsheet export.

---

## Project Structure

```
n8n-dashboard-project/
├── workflow/
│   └── auto-dashboard-workflow.json   ← import into n8n
├── backend/
│   ├── main.py                        ← FastAPI app (Python)
│   └── requirements.txt               ← Python dependencies
├── dashboard/
│   └── dashboard.html                 ← open in any browser
└── README.md                          ← this file
```

---

## Architecture

```
Google Sheets (Raw Data tab)
        │  (row added)
        ▼
n8n: Google Sheets Trigger → Read Raw Data → Python Pre-clean (Code node)
        │  HTTP POST /api/ingest
        ▼
FastAPI backend (Python + pandas)
   - cleans, type-coerces, fills blanks, dedupes
   - stores clean rows in SQLite
   - also mirrors cleaned rows back to the "Dashboard Data" sheet tab
        │  HTTP GET /api/dashboard
        ▼
dashboard.html (browser)
   - fetches live JSON, renders KPIs + charts + searchable table
   - auto-refreshes on a timer
```

---

## Detailed Setup Steps

### Step 1 — Create your Google Sheet

1. Create a spreadsheet at [sheets.google.com](https://sheets.google.com).
2. Rename the first tab to exactly **`Raw Data`**. Add headers such as
   `date, category, amount` (any names work — see the pattern-matching
   note below).
3. Add a second tab named **`Dashboard Data`**, left empty. n8n mirrors
   cleaned rows here for a human-readable backup (the live dashboard
   itself reads from the backend, not this tab).

   Column name patterns the backend auto-detects:
   - **date / day / month** → parsed and normalized to `YYYY-MM-DD`
   - **amount / total / value / price / count / qty** → coerced to a number
   - **category / type / group / name** → used for grouping/charting,
     blanks auto-filled as `"Uncategorized"`

### Step 2 — Set up the Python backend

1. Make sure you have **Python 3.9+** installed.
2. From the `backend/` folder:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
4. Confirm it's running: open `http://localhost:8000` in a browser — you
   should see `{"status":"ok","message":"Auto Dashboard backend running"}`.
5. The backend auto-creates `backend/dashboard.db` (SQLite) on first run.
   No database setup needed.

   **Endpoints:**
   - `POST /api/ingest` — receives `{"rows": [...]}`, cleans with pandas,
     stores new rows, returns the cleaned rows
   - `GET /api/data` — all currently stored clean rows
   - `GET /api/dashboard` — pre-aggregated totals/averages/breakdowns for
     the dashboard
   - `DELETE /api/data` — wipes stored data (handy while testing)

### Step 3 — Get an n8n instance

- **n8n Cloud** (easiest): sign up free at [n8n.io](https://n8n.io).
- **Self-hosted**: `npx n8n`, or Docker:
  `docker run -it --rm -p 5678:5678 n8nio/n8n`.

> If your backend runs on your own machine and n8n runs in Docker or the
> cloud, `localhost:8000` won't be reachable from n8n — use your machine's
> LAN IP, a tunnel (e.g. `ngrok http 8000`), or deploy the backend
> somewhere n8n can reach (Render, Railway, Fly.io, a VPS, etc.), then
> update the URL in the workflow's HTTP Request node.

### Step 4 — Import and configure the workflow

1. In n8n: **Workflows → Import from File** →
   `workflow/auto-dashboard-workflow.json`.
2. You'll see: **Google Sheets Trigger → Read Raw Data → Python Pre-clean
   → Send to Python Backend → Mirror to Dashboard Data Sheet**, plus a
   standalone **Notify on Error** node.
3. On both Google Sheets nodes, connect your Google account (OAuth) and
   select your spreadsheet + the correct tab (`Raw Data` / `Dashboard
   Data`).
4. Open **Python Pre-clean** — this is an n8n Code node set to **Python**
   mode. It runs in n8n's built-in Pyodide sandbox (standard library
   only, no pip installs, no network access) and just trims/filters
   before the real cleaning happens in the backend.
5. Open **Send to Python Backend** (HTTP Request node) and update the URL
   if your backend isn't at `http://localhost:8000`.
6. Click **Active** (top right) to turn the workflow on.

### Step 5 — (Recommended) Set up error alerts

1. Create a small second n8n workflow: **Error Trigger** → Slack/Email
   node.
2. In the main workflow's **Settings → Error Workflow**, select it, so
   you're notified if the Google API, n8n, or the backend ever fails.

### Step 6 — Open the dashboard

1. Open `dashboard/dashboard.html` (double-click it, or serve it with
   `python3 -m http.server` from the `dashboard/` folder for full
   reliability, or host it on GitHub Pages/Netlify).
2. Enter your backend's URL in the **Backend API URL** field (defaults to
   `http://localhost:8000`).
3. Pick an auto-refresh interval and click **Refresh**.
4. You'll see KPI cards, a bar chart, a trend line, a donut chart, and a
   searchable table of every clean row — all sourced live from the
   backend's `/api/dashboard` endpoint.

### Step 7 — Test the full loop

1. Add a new row to `Raw Data` in Google Sheets.
2. Within your n8n trigger's poll interval, it fires → Python pre-clean →
   backend cleans with pandas + stores it → mirrors to `Dashboard Data`.
3. On the dashboard's next auto-refresh (or click **Refresh**), the new
   data appears in the KPIs, charts, and table.

---

## Customizing

- **Different columns?** Edit the regex patterns (`NUM_PATTERN`,
  `DATE_PATTERN`, `CAT_PATTERN`) near the top of `backend/main.py`.
- **A real database instead of SQLite?** Swap the `sqlite3` calls in
  `main.py` for `psycopg2`/`SQLAlchemy` and point at Postgres/MySQL — the
  API shape stays the same, so the n8n workflow and dashboard don't need
  to change.
- **Deploying the backend?** Any host that runs a Python process works
  (Render, Railway, Fly.io, a VPS with `systemd` + `uvicorn`, or a Docker
  container). Just update the URLs in the n8n HTTP Request node and in
  the dashboard's Backend API URL field.
- **File uploads instead of manual sheet edits?** Add a Google Drive
  Trigger node before the Sheets read step, and drop CSV/Excel files into
  a watched folder.

## Maruti Suzuki Car Dashboard
Car dashboard: http://localhost:5500/dashboard.html
n8n editor: http://localhost:5678
Python API docs: http://localhost:8000/docs
Start the dashboard server from the dashboard folder: py -3.11 -m http.server 5500
The car figures are a December 2024/2025 workbook snapshot. Refresh reloads the page; the included n8n workflow does not update the car figures.
