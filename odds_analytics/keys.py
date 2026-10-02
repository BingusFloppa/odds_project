from __future__ import annotations

from pathlib import Path

from .config import Settings


def read_keys() -> list[str]:
    path: Path = Settings.API_KEYS_FILE
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_keys(keys: list[str]) -> None:
    Settings.API_KEYS_FILE.write_text(
        "".join(f"{key.strip()}\n" for key in keys if key.strip()),
        encoding="utf-8",
    )


def add_key(key: str) -> bool:
    clean_key = key.strip()
    if not clean_key:
        return False
    keys = read_keys()
    if clean_key in keys:
        return False
    keys.append(clean_key)
    write_keys(keys)
    return True


def remove_all_keys() -> None:
    write_keys([])


def order_keys(keys: list[str], balances: dict[str, int]) -> list[str]:
    return sorted(keys, key=lambda key: balances.get(key, -1), reverse=True)
