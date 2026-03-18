"""Seed demo data for the ticketing DB service."""

from __future__ import annotations

import argparse
from pathlib import Path

from ticketing_api.database import DEFAULT_DB_PATH, SQLiteDatabase
from ticketing_api.repository import TicketingRepository
from ticketing_api.service import TicketingService


def seed_demo_data(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    db_path = Path(db_path)
    db_path.unlink(missing_ok=True)

    service = TicketingService(TicketingRepository(SQLiteDatabase(db_path)))
    service.initialize()
    service.seed_demo_data()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo ticketing data")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    seed_demo_data(args.db_path)


if __name__ == "__main__":
    main()
