from __future__ import annotations

import time
from datetime import datetime, timedelta

import pandas as pd

from .api import OddsApiClient
from .betting_math import (
    biv_poisson_matrix,
    cache_key,
    calculate_bivariate_params,
    get_true_prob,
    resolve_asian_hcap,
    resolve_asian_total,
)
from .db import get_connection, init_db, query_df
from .repository import get_bookmaker_settings, upsert_bookmaker


def _parse_score(score: str) -> tuple[int, int]:
    home, away = score.split(":", 1)
    return int(home), int(away)


def _request_first_success(api, api_keys, method, *args):
    for key in api_keys:
        response = method(key, *args)
        if response.status_code == 200:
            return response
        if response.status_code not in {401, 429}:
            return response
    return None


def load_data() -> pd.DataFrame:
    init_db()
    return query_df(
        """
        SELECT
            TO_CHAR(o.period, 'DD.MM.YYYY HH24:MI:SS') AS "Parsed_Sort",
            TO_CHAR(o.period, 'DD.MM.YYYY HH24:MI') AS "Parsed",
            TO_CHAR(o.commence_time, 'DD.MM.YYYY HH24:MI') AS "Commence (UTC)",
            o.match_result AS "Score",
            o.league_key AS "League Key",
            COALESCE(l.name, o.league) AS "League Name",
            o.match AS "Match",
            COALESCE(b.name, o.bookmaker) AS "Bookmaker",
            COALESCE(
                b.bookmaker_key,
                o.bookmaker_key,
                'legacy:' || LOWER(REPLACE(COALESCE(o.bookmaker, ''), ' ', '-'))
            ) AS "Bookmaker Key",
            o.odds_1 AS "Odds 1",
            o.odds_x AS "Odds X",
            o.odds_2 AS "Odds 2",
            o.t_line AS "Total",
            o.odds_over AS "Odds Over",
            o.odds_under AS "Odds Under",
            o.h_line AS "Handicap 1",
            o.odds_h1 AS "Odds H1",
            o.odds_h2 AS "Odds H2"
        FROM odds_data o
        LEFT JOIN leagues l
            ON l.id = o.league_id OR l.league_key = o.league_key
        LEFT JOIN bookmakers b
            ON b.id = o.bookmaker_id OR LOWER(b.name) = LOWER(o.bookmaker)
        """
    )


def load_bets() -> tuple[pd.DataFrame, float]:
    df = query_df(
        """
        SELECT
            TO_CHAR(commence_time, 'DD.MM.YYYY HH24:MI') AS "Commence Time",
            league AS "League",
            match AS "Match",
            bookmaker AS "Bookmaker",
            market AS "Outcome",
            market_size AS "Market Size",
            odds AS "Odds",
            true_odds AS "True Odds",
            diff AS "Edge",
            match_result AS "Score",
            profit AS "Profit (U)"
        FROM bets
        ORDER BY commence_time DESC, match
        """
    )
    profit = query_df(
        "SELECT COALESCE(SUM(profit), 0) AS total_profit FROM bets WHERE profit IS NOT NULL"
    )
    return df, float(profit.iloc[0]["total_profit"])


def update_match_results(api: OddsApiClient, api_keys: list[str], progress_callback=None) -> int:
    threshold = datetime.utcnow() - timedelta(hours=2)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT league_key
            FROM odds_data
            WHERE commence_time <= %s
              AND match_result IS NULL
              AND league_key IS NOT NULL
            """,
            (threshold,),
        )
        leagues = [row[0] for row in cur.fetchall()]
        if not leagues:
            return 0

        updated = 0
        for idx, league_key in enumerate(leagues, start=1):
            if progress_callback:
                progress_callback(
                    idx / len(leagues),
                    f"Checking scores: {league_key}",
                )

            response = _request_first_success(
                api, api_keys, api.get_scores, league_key
            )
            if response is None or response.status_code != 200:
                continue

            for game in response.payload:
                if not game.get("completed") or not game.get("scores"):
                    continue

                home = game.get("home_team")
                away = game.get("away_team")
                scores = game.get("scores") or []
                home_score = next(
                    (item["score"] for item in scores if item["name"] == home),
                    None,
                )
                away_score = next(
                    (item["score"] for item in scores if item["name"] == away),
                    None,
                )
                if home_score is None or away_score is None:
                    continue

                cur.execute(
                    """
                    UPDATE odds_data
                    SET match_result = %s
                    WHERE league_key = %s
                      AND match = %s
                      AND match_result IS NULL
                    """,
                    (
                        f"{home_score}:{away_score}",
                        league_key,
                        f"{home} - {away}",
                    ),
                )
                updated += cur.rowcount

            time.sleep(0.05)

        conn.commit()
        return updated


def process_calculations_and_bets(progress_callback=None) -> None:
    settings = get_bookmaker_settings()
    calc_bookies = {key for key, value in settings.items() if value["calc_odds"]}
    bet_bookies = {key for key, value in settings.items() if value["for_bets"]}

    if not calc_bookies and not bet_bookies:
        return

    with get_connection() as conn, conn.cursor() as cur:
        # Settle open bets.
        cur.execute(
            """
            SELECT b.id, b.market, b.market_size, b.odds, o.match_result
            FROM bets b
            JOIN odds_data o
              ON b.match = o.match
             AND o.match_result IS NOT NULL
            WHERE b.match_result IS NULL
            """
        )
        for bet_id, market, market_size, odds, match_result in cur.fetchall():
            try:
                home_score, away_score = _parse_score(match_result)
                diff = home_score - away_score
                total = home_score + away_score

                if market == "1":
                    profit = float(odds) - 1.0 if diff > 0 else -1.0
                elif market == "X":
                    profit = float(odds) - 1.0 if diff == 0 else -1.0
                elif market == "2":
                    profit = float(odds) - 1.0 if diff < 0 else -1.0
                elif market == "Over":
                    profit = resolve_asian_total(
                        total, float(market_size), float(odds), True
                    )
                elif market == "Under":
                    profit = resolve_asian_total(
                        total, float(market_size), float(odds), False
                    )
                elif market == "H1":
                    profit = resolve_asian_hcap(
                        diff, float(market_size), float(odds)
                    )
                elif market == "H2":
                    profit = resolve_asian_hcap(
                        -diff, -float(market_size), float(odds)
                    )
                else:
                    continue

                cur.execute(
                    "UPDATE bets SET match_result = %s, profit = %s WHERE id = %s",
                    (match_result, profit, bet_id),
                )
            except (TypeError, ValueError):
                continue

        conn.commit()

        df = load_data()
        if df.empty:
            return

        df = df[df["Bookmaker Key"].isin(calc_bookies | bet_bookies)].copy()
        df["commence_dt"] = pd.to_datetime(
            df["Commence (UTC)"],
            format="%d.%m.%Y %H:%M",
            errors="coerce",
        )
        df = df[
            (df["Score"].isna())
            | (df["Score"].isin(["None", ""]))
        ]
        df = df.sort_values("Parsed_Sort", ascending=False).drop_duplicates(
            subset=["Match", "Bookmaker Key"]
        )

        now_utc = datetime.utcnow()
        next_24h = now_utc + timedelta(hours=24)

        total_rows = len(df)
        for index, (_, row) in enumerate(df.iterrows(), start=1):
            if progress_callback and (
                index == 1 or index % max(1, total_rows // 20) == 0
            ):
                progress_callback(
                    index / max(1, total_rows),
                    f"Calculating probabilities: {index}/{total_rows}",
                )

            values = [
                row["Odds 1"],
                row["Odds X"],
                row["Odds 2"],
                row["Total"],
                row["Odds Over"],
                row["Odds Under"],
                row["Handicap 1"],
                row["Odds H1"],
                row["Odds H2"],
            ]
            key = cache_key(*values)
            cur.execute(
                "SELECT l1, l2, rho FROM biv_cache WHERE hash_key = %s",
                (key,),
            )
            cached = cur.fetchone()

            if cached:
                l1, l2, rho = cached
            else:
                try:
                    l1, l2, rho, error = calculate_bivariate_params(*values)
                    cur.execute(
                        """
                        INSERT INTO biv_cache (hash_key, l1, l2, rho, error)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (hash_key) DO NOTHING
                        """,
                        (key, l1, l2, rho, error),
                    )
                    conn.commit()
                except (TypeError, ValueError, ZeroDivisionError):
                    continue

            commence_dt = row["commence_dt"]
            within_24h = (
                pd.notna(commence_dt)
                and now_utc < commence_dt.to_pydatetime() <= next_24h
            )
            if row["Bookmaker Key"] not in bet_bookies or not within_24h:
                continue

            matrix = biv_poisson_matrix(float(l1), float(l2), float(rho))
            probabilities = {
                "1": get_true_prob(matrix, "1"),
                "X": get_true_prob(matrix, "X"),
                "2": get_true_prob(matrix, "2"),
                "Over": (
                    get_true_prob(matrix, "Over", row["Total"])
                    if pd.notna(row["Total"])
                    else 0
                ),
                "Under": (
                    get_true_prob(matrix, "Under", row["Total"])
                    if pd.notna(row["Total"])
                    else 0
                ),
                "H1": (
                    get_true_prob(matrix, "H1", row["Handicap 1"])
                    if pd.notna(row["Handicap 1"])
                    else 0
                ),
                "H2": (
                    get_true_prob(matrix, "H2", -row["Handicap 1"])
                    if pd.notna(row["Handicap 1"])
                    else 0
                ),
            }
            odds_map = {
                "1": row["Odds 1"],
                "X": row["Odds X"],
                "2": row["Odds 2"],
                "Over": row["Odds Over"],
                "Under": row["Odds Under"],
                "H1": row["Odds H1"],
                "H2": row["Odds H2"],
            }
            size_map = {
                "1": "",
                "X": "",
                "2": "",
                "Over": row["Total"],
                "Under": row["Total"],
                "H1": row["Handicap 1"],
                "H2": (
                    -row["Handicap 1"]
                    if pd.notna(row["Handicap 1"])
                    else None
                ),
            }

            for market, probability in probabilities.items():
                market_odds = odds_map[market]
                if pd.isna(market_odds) or probability <= 0:
                    continue

                true_odds = 1 / probability
                edge = float(market_odds) - true_odds
                if edge <= 0:
                    continue

                size = size_map[market]
                if size is None or (
                    isinstance(size, float) and pd.isna(size)
                ):
                    continue

                if market in {"H1", "H2"}:
                    size_str = f"{float(size):+g}"
                elif size != "":
                    size_str = f"{float(size):g}"
                else:
                    size_str = ""

                cur.execute(
                    """
                    INSERT INTO bets (
                        commence_time, league, match, bookmaker, market,
                        market_size, odds, true_odds, diff, match_result, profit,
                        league_id, bookmaker_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        NULL, NULL,
                        (SELECT id FROM leagues WHERE league_key = %s),
                        (SELECT id FROM bookmakers WHERE bookmaker_key = %s)
                    )
                    ON CONFLICT (match, bookmaker, market, market_size) DO NOTHING
                    """,
                    (
                        commence_dt.to_pydatetime(),
                        row["League Key"],
                        row["Match"],
                        row["Bookmaker"],
                        market,
                        size_str,
                        float(market_odds),
                        true_odds,
                        edge,
                        row["League Key"],
                        row["Bookmaker Key"],
                    ),
                )

        conn.commit()


def fetch_selected_leagues_data(
    selected_leagues: list[dict],
    api_keys: list[str],
    progress_callback=None,
) -> tuple[int, int]:
    if not selected_leagues:
        raise ValueError("No leagues selected.")
    if not api_keys:
        raise ValueError("No API keys configured.")

    init_db()
    api = OddsApiClient()
    records_added = 0

    with get_connection() as conn, conn.cursor() as cur:
        period = datetime.now()

        for index, league in enumerate(selected_leagues, start=1):
            league_key = league["league_key"]
            league_title = league["name"]

            if progress_callback:
                progress_callback(
                    (index - 1) / len(selected_leagues),
                    f"Fetching: {league_title}",
                )

            response = _request_first_success(
                api,
                api_keys,
                api.get_odds,
                league_key,
            )
            if response is None or response.status_code != 200:
                continue

            cur.execute(
                "SELECT id FROM leagues WHERE league_key = %s",
                (league_key,),
            )
            league_row = cur.fetchone()
            league_id = league_row[0] if league_row else None

            for game in response.payload:
                home = game.get("home_team")
                away = game.get("away_team")
                match = f"{home} - {away}"

                commence_time = None
                raw_time = game.get("commence_time")
                if raw_time:
                    try:
                        commence_time = datetime.strptime(
                            raw_time,
                            "%Y-%m-%dT%H:%M:%SZ",
                        )
                    except ValueError:
                        pass

                for bookmaker in game.get("bookmakers", []):
                    bookmaker_name = (
                        bookmaker.get("title") or "Unknown"
                    ).strip()
                    bookmaker_id, bookmaker_key = upsert_bookmaker(
                        cur,
                        bookmaker.get("key"),
                        bookmaker_name,
                    )

                    markets = bookmaker.get("markets", [])
                    market_keys = {
                        market.get("key") for market in markets
                    }
                    if not {"h2h", "totals", "spreads"}.issubset(
                        market_keys
                    ):
                        continue

                    o1 = ox = o2 = tl = oo = ou = hl = oh1 = oh2 = None
                    for market in markets:
                        outcomes = market.get("outcomes", [])
                        if market.get("key") == "h2h":
                            outcome_map = {
                                item["name"]: item["price"]
                                for item in outcomes
                            }
                            o1 = outcome_map.get(home)
                            ox = outcome_map.get("Draw")
                            o2 = outcome_map.get(away)
                        elif market.get("key") == "totals":
                            over = next(
                                (
                                    item
                                    for item in outcomes
                                    if item.get("name") == "Over"
                                ),
                                None,
                            )
                            under = next(
                                (
                                    item
                                    for item in outcomes
                                    if item.get("name") == "Under"
                                ),
                                None,
                            )
                            if over and under:
                                tl = float(over["point"])
                                oo = float(over["price"])
                                ou = float(under["price"])
                        elif market.get("key") == "spreads":
                            home_line = next(
                                (
                                    item
                                    for item in outcomes
                                    if item.get("name") == home
                                ),
                                None,
                            )
                            away_line = next(
                                (
                                    item
                                    for item in outcomes
                                    if item.get("name") == away
                                ),
                                None,
                            )
                            if home_line and away_line:
                                hl = float(home_line["point"])
                                oh1 = float(home_line["price"])
                                oh2 = float(away_line["price"])

                    if not all(
                        value is not None
                        for value in [o1, ox, o2, tl, oo, ou, hl, oh1, oh2]
                    ):
                        continue

                    margin = (
                        (1 / o1) + (1 / ox) + (1 / o2) - 1
                    ) * 100

                    cur.execute(
                        """
                        INSERT INTO odds_data (
                            period, league, match, bookmaker, market_type,
                            odds_1, odds_x, odds_2, margin,
                            t_line, odds_over, odds_under,
                            h_line, odds_h1, odds_h2,
                            league_key, commence_time,
                            league_id, bookmaker_id, bookmaker_key
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s,
                            %s, %s,
                            %s, %s, %s
                        )
                        """,
                        (
                            period,
                            league_title,
                            match,
                            bookmaker_name,
                            "Line",
                            o1,
                            ox,
                            o2,
                            margin,
                            tl,
                            oo,
                            ou,
                            hl,
                            oh1,
                            oh2,
                            league_key,
                            commence_time,
                            league_id,
                            bookmaker_id,
                            bookmaker_key,
                        ),
                    )
                    records_added += 1

            time.sleep(0.05)

        conn.commit()

    scores_updated = update_match_results(
        api,
        api_keys,
        progress_callback,
    )
    process_calculations_and_bets(progress_callback)
    return records_added, scores_updated


def build_display_frame(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    if df.empty:
        return df

    settings = get_bookmaker_settings()
    calc_keys = {
        key for key, value in settings.items() if value["calc_odds"]
    }
    df = df[df["Bookmaker Key"].isin(calc_keys)].copy()
    if df.empty:
        return df

    df = df.sort_values("Parsed_Sort", ascending=False).drop_duplicates(
        subset=["Match", "Bookmaker Key"]
    )

    rows = []
    for _, row in df.iterrows():
        score = row["Score"]
        results = {
            "1": "",
            "X": "",
            "2": "",
            "Over": "",
            "Under": "",
            "H1": "",
            "H2": "",
        }

        if isinstance(score, str) and ":" in score:
            try:
                home_score, away_score = _parse_score(score)
                diff = home_score - away_score
                total = home_score + away_score

                for market, odds in [
                    ("1", row["Odds 1"]),
                    ("X", row["Odds X"]),
                    ("2", row["Odds 2"]),
                ]:
                    if pd.isna(odds):
                        continue
                    won = {
                        "1": diff > 0,
                        "X": diff == 0,
                        "2": diff < 0,
                    }[market]
                    results[market] = round(
                        float(odds) - 1 if won else -1,
                        2,
                    )

                if pd.notna(row["Total"]):
                    if pd.notna(row["Odds Over"]):
                        results["Over"] = round(
                            resolve_asian_total(
                                total,
                                row["Total"],
                                row["Odds Over"],
                                True,
                            ),
                            2,
                        )
                    if pd.notna(row["Odds Under"]):
                        results["Under"] = round(
                            resolve_asian_total(
                                total,
                                row["Total"],
                                row["Odds Under"],
                                False,
                            ),
                            2,
                        )

                if pd.notna(row["Handicap 1"]):
                    if pd.notna(row["Odds H1"]):
                        results["H1"] = round(
                            resolve_asian_hcap(
                                diff,
                                row["Handicap 1"],
                                row["Odds H1"],
                            ),
                            2,
                        )
                    if pd.notna(row["Odds H2"]):
                        results["H2"] = round(
                            resolve_asian_hcap(
                                -diff,
                                -row["Handicap 1"],
                                row["Odds H2"],
                            ),
                            2,
                        )
            except (TypeError, ValueError):
                pass

        k1, kx, k2 = (
            row["Odds 1"],
            row["Odds X"],
            row["Odds 2"],
        )
        margin_1x2 = (
            ((1 / k1) + (1 / kx) + (1 / k2) - 1) * 100
            if all(pd.notna(x) and x for x in [k1, kx, k2])
            else None
        )
        margin_total = (
            ((1 / row["Odds Over"]) + (1 / row["Odds Under"]) - 1) * 100
            if all(
                pd.notna(x) and x
                for x in [row["Odds Over"], row["Odds Under"]]
            )
            else None
        )
        margin_hcap = (
            ((1 / row["Odds H1"]) + (1 / row["Odds H2"]) - 1) * 100
            if all(
                pd.notna(x) and x
                for x in [row["Odds H1"], row["Odds H2"]]
            )
            else None
        )

        cache_key_value = cache_key(
            k1,
            kx,
            k2,
            row["Total"],
            row["Odds Over"],
            row["Odds Under"],
            row["Handicap 1"],
            row["Odds H1"],
            row["Odds H2"],
        )
        l1, l2, rho, error = cache.get(
            cache_key_value,
            (None, None, None, None),
        )

        true_odds = {}
        if l1 is not None:
            matrix = biv_poisson_matrix(
                float(l1),
                float(l2),
                float(rho),
            )
            p1 = get_true_prob(matrix, "1")
            px = get_true_prob(matrix, "X")
            p2 = get_true_prob(matrix, "2")
            true_odds = {
                "1": 1 / p1 if p1 > 0 else None,
                "X": 1 / px if px > 0 else None,
                "2": 1 / p2 if p2 > 0 else None,
                "Over": (
                    1 / get_true_prob(matrix, "Over", row["Total"])
                    if pd.notna(row["Total"])
                    and get_true_prob(matrix, "Over", row["Total"]) > 0
                    else None
                ),
                "Under": (
                    1 / get_true_prob(matrix, "Under", row["Total"])
                    if pd.notna(row["Total"])
                    and get_true_prob(matrix, "Under", row["Total"]) > 0
                    else None
                ),
                "H1": (
                    1 / get_true_prob(matrix, "H1", row["Handicap 1"])
                    if pd.notna(row["Handicap 1"])
                    and get_true_prob(matrix, "H1", row["Handicap 1"]) > 0
                    else None
                ),
                "H2": (
                    1 / get_true_prob(
                        matrix,
                        "H2",
                        -row["Handicap 1"],
                    )
                    if pd.notna(row["Handicap 1"])
                    and get_true_prob(
                        matrix,
                        "H2",
                        -row["Handicap 1"],
                    ) > 0
                    else None
                ),
            }

        markets = [
            ("1", "", row["Odds 1"], margin_1x2),
            ("X", "", row["Odds X"], margin_1x2),
            ("2", "", row["Odds 2"], margin_1x2),
            ("Over", row["Total"], row["Odds Over"], margin_total),
            ("Under", row["Total"], row["Odds Under"], margin_total),
            ("H1", row["Handicap 1"], row["Odds H1"], margin_hcap),
            (
                "H2",
                -row["Handicap 1"]
                if pd.notna(row["Handicap 1"])
                else None,
                row["Odds H2"],
                margin_hcap,
            ),
        ]

        for market, size, odds, margin in markets:
            fair = true_odds.get(market)
            edge = (
                float(odds) - fair
                if pd.notna(odds) and fair
                else None
            )
            rows.append(
                {
                    "Parsed": row["Parsed"],
                    "Commence (UTC)": row["Commence (UTC)"],
                    "Score": (
                        row["Score"]
                        if pd.notna(row["Score"])
                        else ""
                    ),
                    "League": row["League Key"],
                    "Match": row["Match"],
                    "Bookmaker": row["Bookmaker"],
                    "Outcome": market,
                    "Size": (
                        ""
                        if size is None
                        or (
                            isinstance(size, float)
                            and pd.isna(size)
                        )
                        else size
                    ),
                    "Odds": odds,
                    "Margin %": margin,
                    "Result": results[market],
                    "L1": l1,
                    "L2": l2,
                    "G (Rho)": rho,
                    "Error": error,
                    "True Odds": fair,
                    "Diff": edge,
                }
            )

    return pd.DataFrame(rows)
