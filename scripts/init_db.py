from odds_analytics.db import init_db
from odds_analytics.repository import (
    bootstrap_reference_data,
    sync_bookmakers_from_odds_data,
)


if __name__ == "__main__":
    init_db()
    bootstrap_reference_data()
    sync_bookmakers_from_odds_data()
    print("Database schema initialized and reference data synchronized.")
