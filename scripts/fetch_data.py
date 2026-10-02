from odds_analytics.db import init_db
from odds_analytics.keys import read_keys
from odds_analytics.repository import bootstrap_reference_data, list_leagues
from odds_analytics.service import fetch_selected_leagues_data


if __name__ == "__main__":
    init_db()
    bootstrap_reference_data()

    leagues = list_leagues()
    selected = (
        leagues[leagues["Select"] == True]
        .rename(
            columns={
                "League Key": "league_key",
                "League Name": "name",
            }
        )
        .to_dict("records")
    )
    keys = read_keys()

    if not keys:
        raise SystemExit("No API keys found in api_keys.txt")

    added, settled = fetch_selected_leagues_data(selected, keys)
    print(f"Added {added} odds rows; updated {settled} match results.")
