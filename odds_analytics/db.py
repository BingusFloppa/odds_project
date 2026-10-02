from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2

from .config import Settings


def get_connection():
    return psycopg2.connect(**Settings.db_params())


def init_db() -> None:
    schema = Path(Settings.SCHEMA_FILE).read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
            _backfill_reference_ids(cur)
        conn.commit()


def _backfill_reference_ids(cur) -> None:
    cur.execute(
        """
        UPDATE odds_data o
        SET league_id = l.id
        FROM leagues l
        WHERE o.league_id IS NULL
          AND o.league_key = l.league_key
        """
    )
    cur.execute(
        """
        UPDATE odds_data o
        SET bookmaker_id = b.id,
            bookmaker_key = COALESCE(o.bookmaker_key, b.bookmaker_key)
        FROM bookmakers b
        WHERE o.bookmaker_id IS NULL
          AND LOWER(o.bookmaker) = LOWER(b.name)
        """
    )
    cur.execute(
        """
        UPDATE bets bet
        SET league_id = l.id
        FROM leagues l
        WHERE bet.league_id IS NULL
          AND bet.league = l.league_key
        """
    )
    cur.execute(
        """
        UPDATE bets bet
        SET bookmaker_id = b.id
        FROM bookmakers b
        WHERE bet.bookmaker_id IS NULL
          AND LOWER(bet.bookmaker) = LOWER(b.name)
        """
    )


def query_df(query: str, params=None) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def clear_runtime_data() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE bets, biv_cache, odds_data RESTART IDENTITY CASCADE;")
        conn.commit()
    init_db()
