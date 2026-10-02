from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .config import Settings
from .db import get_connection


def _seed_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def bootstrap_reference_data() -> None:
    """Seed reference tables only when they are empty."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM leagues")
        leagues_empty = cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM bookmakers")
        bookmakers_empty = cur.fetchone()[0] == 0

        if leagues_empty and Path(Settings.LEAGUES_SEED_FILE).exists():
            rows = json.loads(Path(Settings.LEAGUES_SEED_FILE).read_text(encoding="utf-8"))
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO leagues (league_key, name, sport, selected)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (league_key) DO NOTHING
                    """,
                    (
                        row["league_key"],
                        row["name"],
                        row.get("sport", "soccer"),
                        row.get("selected", False),
                    ),
                )

        if bookmakers_empty and Path(Settings.BOOKMAKERS_SEED_FILE).exists():
            rows = json.loads(Path(Settings.BOOKMAKERS_SEED_FILE).read_text(encoding="utf-8"))
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO bookmakers
                        (bookmaker_key, name, calc_odds, for_bets, build_clusters)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (bookmaker_key) DO NOTHING
                    """,
                    (
                        row["bookmaker_key"],
                        row["name"],
                        row.get("calc_odds", False),
                        row.get("for_bets", False),
                        row.get("build_clusters", False),
                    ),
                )
        conn.commit()

    # Import any bookmakers already present in an older odds_data table, then
    # backfill foreign-key references now that the reference rows exist.
    sync_bookmakers_from_odds_data()
    with get_connection() as conn, conn.cursor() as cur:
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
        conn.commit()


def list_leagues() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT
                league_key AS "League Key",
                name AS "League Name",
                selected AS "Select",
                sport AS "Sport",
                updated_at AS "Updated"
            FROM leagues
            WHERE is_active = TRUE
            ORDER BY name
            """,
            conn,
        )


def sync_leagues(api_leagues: list[dict]) -> int:
    count = 0
    with get_connection() as conn, conn.cursor() as cur:
        for league in api_leagues:
            key = (league.get("key") or "").strip()
            title = (league.get("title") or key).strip()
            group = (league.get("group") or "soccer").strip()
            if not key:
                continue
            cur.execute(
                """
                INSERT INTO leagues (league_key, name, sport)
                VALUES (%s, %s, %s)
                ON CONFLICT (league_key) DO UPDATE
                SET name = EXCLUDED.name,
                    sport = EXCLUDED.sport,
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, title, group),
            )
            count += 1
        conn.commit()
    return count


def save_league_settings(rows: list[dict]) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                UPDATE leagues
                SET selected = %s, updated_at = CURRENT_TIMESTAMP
                WHERE league_key = %s
                """,
                (bool(row["Select"]), row["League Key"]),
            )
        conn.commit()


def list_bookmakers() -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT
                bookmaker_key AS "Bookmaker Key",
                name AS "Bookmaker",
                calc_odds AS "Calc Odds",
                for_bets AS "For Bets",
                build_clusters AS "Build Clusters",
                updated_at AS "Updated"
            FROM bookmakers
            WHERE is_active = TRUE
            ORDER BY name
            """,
            conn,
        )


def get_bookmaker_settings() -> dict[str, dict[str, bool]]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bookmaker_key, calc_odds, for_bets, build_clusters
            FROM bookmakers
            WHERE is_active = TRUE
            """
        )
        return {
            row[0]: {
                "calc_odds": row[1],
                "for_bets": row[2],
                "build_clusters": row[3],
            }
            for row in cur.fetchall()
        }


def upsert_bookmaker(cur, bookmaker_key: str | None, name: str) -> tuple[int, str]:
    safe_key = (bookmaker_key or "").strip() or f"legacy:{_seed_slug(name)}"
    clean_name = name.strip()

    cur.execute(
        """
        SELECT id, bookmaker_key
        FROM bookmakers
        WHERE LOWER(name) = LOWER(%s)
        ORDER BY id
        LIMIT 1
        """,
        (clean_name,),
    )
    existing = cur.fetchone()

    if existing and existing[1] != safe_key:
        cur.execute(
            """
            UPDATE bookmakers
            SET bookmaker_key = %s,
                is_active = TRUE,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (safe_key, existing[0]),
        )
        return existing[0], safe_key

    cur.execute(
        """
        INSERT INTO bookmakers (bookmaker_key, name)
        VALUES (%s, %s)
        ON CONFLICT (bookmaker_key) DO UPDATE
        SET name = EXCLUDED.name,
            is_active = TRUE,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, bookmaker_key
        """,
        (safe_key, clean_name),
    )
    result = cur.fetchone()
    return result[0], result[1]


def sync_bookmaker(bookmaker_key: str | None, name: str) -> tuple[int, str]:
    """Upsert one bookmaker using its own transaction."""
    with get_connection() as conn, conn.cursor() as cur:
        result = upsert_bookmaker(cur, bookmaker_key, name)
        conn.commit()
        return result


def sync_bookmakers_from_odds_data() -> int:
    count = 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT bookmaker
            FROM odds_data
            WHERE bookmaker IS NOT NULL
              AND bookmaker <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM bookmakers b
                  WHERE LOWER(b.name) = LOWER(odds_data.bookmaker)
              )
            ORDER BY bookmaker
            """
        )
        names = [row[0] for row in cur.fetchall()]
        for name in names:
            key = f"legacy:{_seed_slug(name)}"
            cur.execute(
                """
                INSERT INTO bookmakers (bookmaker_key, name)
                VALUES (%s, %s)
                ON CONFLICT (bookmaker_key) DO NOTHING
                """,
                (key, name),
            )
            count += cur.rowcount
        conn.commit()
    return count
