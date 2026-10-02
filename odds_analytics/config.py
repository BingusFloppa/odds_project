from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_DIR = PROJECT_ROOT / "db"

load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    DB_NAME = os.getenv("DB_NAME", "odds_db")
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")

    ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
    ODDS_API_TIMEOUT = int(os.getenv("ODDS_API_TIMEOUT", "30"))

    API_KEYS_FILE = PROJECT_ROOT / "api_keys.txt"
    SCHEMA_FILE = DB_DIR / "schema.sql"
    LEAGUES_SEED_FILE = DATA_DIR / "leagues_seed.json"
    BOOKMAKERS_SEED_FILE = DATA_DIR / "bookmakers_seed.json"

    @classmethod
    def db_params(cls) -> dict[str, str]:
        return {
            "dbname": cls.DB_NAME,
            "user": cls.DB_USER,
            "password": cls.DB_PASS,
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
        }
