"""
Data access layer for the PnL dashboard.

>>> THIS IS THE ONE PLACE YOU PLUG IN YOUR SQL. <<<

`fetch_pnl_data(start_date, end_date, account_id)` must return a pandas
DataFrame whose schema matches `pnl_data` exactly (see config.REQUIRED_COLUMNS).
The current implementation reads the sample Excel so the dashboard runs
out-of-the-box; replace the body of `_load_from_sql` with your query and flip
`USE_SQL = True`.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config import REQUIRED_COLUMNS

# Flip to True once the SQL query below is wired up.
USE_SQL = False

# Fallback sample file (the workbook you provided), used when USE_SQL is False.
SAMPLE_DATA_PATH = Path(__file__).parent / "data" / "sample_pnl_data.xlsx"


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #
def fetch_pnl_data(
    start_date: str | date,
    end_date: str | date,
    account_id: int | None = None,
) -> pd.DataFrame:
    """Return the PnL rows for [start_date, end_date] (inclusive).

    Parameters
    ----------
    start_date, end_date : 'YYYY-MM-DD' string or datetime.date
    account_id : optional filter; None returns all accounts.

    Returns
    -------
    DataFrame with the `pnl_data` schema (one row per instrument per day).
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    if USE_SQL:
        df = _load_from_sql(start, end, account_id)
    else:
        df = _load_from_sample(start, end, account_id)

    df = _normalise(df)
    _validate(df)
    return df


# --------------------------------------------------------------------------- #
# SQL implementation — REPLACE THIS BODY                                       #
# --------------------------------------------------------------------------- #
def _load_from_sql(start: pd.Timestamp, end: pd.Timestamp,
                   account_id: int | None) -> pd.DataFrame:
    """Run your parameterised query and return a DataFrame.

    Example skeleton (uncomment and adapt to your connection / dialect):

        import sqlalchemy as sa
        engine = sa.create_engine(os.environ["PNL_DB_URL"])
        query = sa.text('''
            SELECT *
            FROM   pnl_data
            WHERE  Date BETWEEN :start AND :end
              AND  (:account_id IS NULL OR AccountId = :account_id)
        ''')
        with engine.connect() as conn:
            return pd.read_sql(query, conn, params={
                "start": start.date(),
                "end": end.date(),
                "account_id": account_id,
            })

    The only contract is: the returned DataFrame must contain the columns in
    config.REQUIRED_COLUMNS (extra columns are fine and simply ignored).
    """
    raise NotImplementedError(
        "Wire up your SQL query in data_source._load_from_sql and set "
        "USE_SQL = True."
    )


# --------------------------------------------------------------------------- #
# Sample fallback so the dashboard runs without a DB                           #
# --------------------------------------------------------------------------- #
def _load_from_sample(start: pd.Timestamp, end: pd.Timestamp,
                      account_id: int | None) -> pd.DataFrame:
    if not SAMPLE_DATA_PATH.exists():
        raise FileNotFoundError(
            f"Sample data not found at {SAMPLE_DATA_PATH}. Either add it or set "
            f"USE_SQL = True and implement _load_from_sql()."
        )
    # Cache the parsed workbook as parquet for fast repeat runs.
    cache = SAMPLE_DATA_PATH.with_suffix(".parquet")
    if cache.exists() and cache.stat().st_mtime >= SAMPLE_DATA_PATH.stat().st_mtime:
        df = pd.read_parquet(cache)
    else:
        df = pd.read_excel(SAMPLE_DATA_PATH, sheet_name="Sheet1")
        try:
            df.to_parquet(cache)
        except Exception:
            pass  # parquet engine optional

    df["Date"] = pd.to_datetime(df["Date"])
    mask = (df["Date"] >= start) & (df["Date"] <= end)
    if account_id is not None:
        mask &= df["AccountId"] == account_id
    return df.loc[mask].copy()


# --------------------------------------------------------------------------- #
# Shared post-processing                                                       #
# --------------------------------------------------------------------------- #
def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    # Make sure the metric columns exist and are numeric; fill gaps with 0.
    numeric = [c for c in REQUIRED_COLUMNS
               if c not in ("Date", "Ticker", "Currency")]
    for col in numeric:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ("Ticker", "Currency"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str)
    return df


def _validate(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"fetch_pnl_data is missing required columns: {missing}")


def available_date_range(account_id: int | None = None) -> tuple[date, date]:
    """Convenience: min/max date available (used to default the dashboard range)."""
    if USE_SQL:
        # Cheap query in production: SELECT MIN(Date), MAX(Date) ...
        raise NotImplementedError("Implement a MIN/MAX(Date) query for SQL mode.")
    df = pd.read_parquet(SAMPLE_DATA_PATH.with_suffix(".parquet")) \
        if SAMPLE_DATA_PATH.with_suffix(".parquet").exists() \
        else pd.read_excel(SAMPLE_DATA_PATH, sheet_name="Sheet1", usecols=["Date", "AccountId"])
    df["Date"] = pd.to_datetime(df["Date"])
    if account_id is not None:
        df = df[df["AccountId"] == account_id]
    return df["Date"].min().date(), df["Date"].max().date()
