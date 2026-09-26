"""
Auto Dashboard Backend
-----------------------
A small FastAPI service that:
  1. Receives raw rows from n8n (POST /api/ingest)
  2. Cleans them with pandas (trim, type coercion, dedupe, fill blanks)
  3. Stores clean rows in a local SQLite database
  4. Serves the dashboard: GET /api/data (raw clean rows) and
     GET /api/dashboard (pre-aggregated totals/averages/breakdowns)

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000

Then point n8n's HTTP Request node at:
    http://localhost:8000/api/ingest

And point dashboard.html's "Backend API URL" field at:
    http://localhost:8000
"""

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = Path(__file__).parent / "dashboard.db"

app = FastAPI(title="Auto Dashboard Backend")

# Allow the dashboard.html file (opened from disk or another host) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

NUM_PATTERN = re.compile(r"amount|total|value|price|count|qty", re.IGNORECASE)
DATE_PATTERN = re.compile(r"date|day|month", re.IGNORECASE)
CAT_PATTERN = re.compile(r"category|type|group|name", re.IGNORECASE)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            row_hash TEXT UNIQUE,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


class IngestPayload(BaseModel):
    rows: List[Dict[str, Any]]


def clean_dataframe(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """Automatic data cleaning: trim, type-coerce, fill blanks, dedupe."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Trim whitespace on every text column
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()

    # Coerce amount/total/value/price/count/qty-style columns to numbers
    for col in df.columns:
        if NUM_PATTERN.search(col):
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r"[^0-9.\-]", "", regex=True),
                errors="coerce",
            ).fillna(0)

    # Normalize date-style columns to YYYY-MM-DD
    for col in df.columns:
        if DATE_PATTERN.search(col):
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")

    # Fill blank category/type/group/name columns instead of dropping the row
    for col in df.columns:
        if CAT_PATTERN.search(col):
            df[col] = df[col].replace("", "Uncategorized").fillna("Uncategorized")

    # Drop rows that are entirely empty, then drop exact duplicate rows
    df = df.dropna(how="all")
    df = df.drop_duplicates()
    return df


@app.post("/api/ingest")
def ingest(payload: IngestPayload) -> Dict[str, Any]:
    """Called by n8n's HTTP Request node with the latest raw rows."""
    df = clean_dataframe(payload.rows)
    conn = get_conn()
    inserted, skipped = 0, 0

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        row_hash = str(row_dict.get("row_number") or hash(frozenset(row_dict.items())))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO records (row_hash, data, created_at) VALUES (?, ?, ?)",
                (row_hash, json.dumps(row_dict, default=str), datetime.now(timezone.utc).isoformat()),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1  # already stored this exact row

    conn.commit()
    conn.close()

    return {
        "inserted": inserted,
        "skipped_duplicates": skipped,
        "cleaned_rows": df.to_dict(orient="records"),
    }


@app.get("/api/data")
def get_data() -> List[Dict[str, Any]]:
    """Returns every clean row currently stored."""
    conn = get_conn()
    rows = conn.execute("SELECT data FROM records ORDER BY id").fetchall()
    conn.close()
    return [json.loads(r["data"]) for r in rows]


@app.get("/api/dashboard")
def get_dashboard() -> Dict[str, Any]:
    """Pre-aggregated data ready for the dashboard's KPI cards and charts."""
    rows = get_data()
    if not rows:
        return {
            "total": 0, "rows": 0, "average": 0, "top_category": None,
            "by_category": {}, "by_date": {}, "raw": [],
        }

    df = pd.DataFrame(rows)
    num_col: Optional[str] = next((c for c in df.columns if NUM_PATTERN.search(c)), None)
    cat_col: str = next((c for c in df.columns if CAT_PATTERN.search(c)), df.columns[0])
    date_col: Optional[str] = next((c for c in df.columns if DATE_PATTERN.search(c)), None)

    total = float(df[num_col].sum()) if num_col else len(df)

    if num_col:
        by_category = df.groupby(cat_col)[num_col].sum().to_dict()
    else:
        by_category = df[cat_col].value_counts().to_dict()

    by_date: Dict[str, float] = {}
    if date_col:
        if num_col:
            by_date = df.groupby(date_col)[num_col].sum().to_dict()
        else:
            by_date = df[date_col].value_counts().to_dict()

    top_category = max(by_category, key=by_category.get) if by_category else None

    return {
        "total": total,
        "rows": len(df),
        "average": (total / len(df)) if len(df) else 0,
        "top_category": top_category,
        "by_category": by_category,
        "by_date": by_date,
        "raw": df.to_dict(orient="records"),
    }


@app.delete("/api/data")
def clear_data() -> Dict[str, str]:
    """Optional: wipe stored data (handy while testing)."""
    conn = get_conn()
    conn.execute("DELETE FROM records")
    conn.commit()
    conn.close()
    return {"status": "cleared"}


@app.get("/")
def root() -> Dict[str, str]:
    return {"status": "ok", "message": "Auto Dashboard backend running"}
