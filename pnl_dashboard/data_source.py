"""
Data access layer for the PnL dashboard.

>>> THIS IS THE ONE PLACE YOU PLUG IN YOUR SQL. <<<

`fetch_pnl_data(start_date, end_date, account_id)` must return a pandas
DataFrame whose schema matches `pnl_data` exactly (see config.REQUIRED_COLUMNS).
`fetch_aum(start_date, end_date, account_id)` returns daily strategy AUM.
The current implementations read the sample Excels so the dashboard runs
out-of-the-box; replace the bodies of `_load_from_sql` / `_load_aum_from_sql`
with your queries and flip `USE_SQL = True`.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config import REQUIRED_COLUMNS, PNL_TO_AUM_ACCOUNT

# Flip to True once the SQL query below is wired up.
USE_SQL = False

# Fallback sample files (the workbooks you provided), used when USE_SQL is False.
SAMPLE_DATA_PATH = Path(__file__).parent / "data" / "sample_pnl_data.xlsx"
SAMPLE_AUM_PATH = Path(__file__).parent / "data" / "sample_aumdetails.xlsx"


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


# --------------------------------------------------------------------------- #
# AUM                                                                          #
# --------------------------------------------------------------------------- #
def fetch_aum(
    start_date: str | date,
    end_date: str | date,
    account_id: int | None = None,
) -> pd.Series:
    """Return a Series of daily strategy AUM indexed by date (one value per day).

    Columns expected from source: AccountId, AUMDetailsId, Date (with timestamp),
    AUMAmount. When a date has several rows, the LATEST TIMESTAMP wins.

    >>> Plug your SQL here too (see _load_aum_from_sql). <<<
    """
    start, end = pd.to_datetime(start_date), pd.to_datetime(end_date)
    aum_account = PNL_TO_AUM_ACCOUNT.get(account_id, account_id)

    if USE_SQL:
        df = _load_aum_from_sql(start, end, aum_account)
    else:
        df = _load_aum_from_sample(aum_account)

    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df["Day"] = df["Date"].dt.normalize()                       # calendar date
    df = df.sort_values(["Day", "Date"])                        # latest ts last
    latest = df.groupby("Day", as_index=True).tail(1)           # keep latest ts
    s = latest.set_index("Day")["AUMAmount"].astype(float).sort_index()
    s = s[(s.index >= start.normalize()) & (s.index <= end.normalize())]
    s.name = "AUM"
    return s


def _load_aum_from_sql(start, end, aum_account) -> pd.DataFrame:
    """Replace with your AUM query (mirror of _load_from_sql).

        SELECT AccountId, AUMDetailsId, Date, AUMAmount
        FROM   aumdetails
        WHERE  Date BETWEEN :start AND :end
          AND  (:acct IS NULL OR AccountId = :acct)
    """
    raise NotImplementedError("Wire up your AUM query in _load_aum_from_sql.")


def _load_aum_from_sample(aum_account) -> pd.DataFrame:
    if not SAMPLE_AUM_PATH.exists():
        raise FileNotFoundError(
            f"Sample AUM not found at {SAMPLE_AUM_PATH}. Add it (the aumdetails "
            f"workbook) or implement _load_aum_from_sql() and set USE_SQL = True."
        )
    df = pd.read_excel(SAMPLE_AUM_PATH)
    if aum_account is not None and "AccountId" in df.columns \
            and (df["AccountId"] == aum_account).any():
        df = df[df["AccountId"] == aum_account]
    return df


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
