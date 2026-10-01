"""Copies MAYA's data from the SQLite database to PostgreSQL (Phase 2's move, decision D3).

    ./.venv/bin/python -m scripts.sqlite_to_postgres            # from DATABASE_URL to POSTGRES_URL
    ./.venv/bin/python -m scripts.sqlite_to_postgres --check    # only compare row counts

Safe to run again: the PostgreSQL tables are emptied first, so the result is always an exact
copy of the SQLite database at that moment. The schema must already exist in PostgreSQL
(`DATABASE_URL=<postgres url> alembic upgrade head`). Never touches the SQLite file.
"""

import sys

from sqlalchemy import create_engine, func, select, text

import app.models  # noqa: F401 — registers every table on Base.metadata
from app.core.config import get_settings
from app.core.db import Base

BATCH = 2000


def counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one() for t in Base.metadata.sorted_tables}


def main() -> None:
    settings = get_settings()
    target_url = settings.postgres_url
    if not target_url:
        sys.exit("Set POSTGRES_URL in apps/api/.env")
    source = create_engine(settings.database_url)
    target = create_engine(target_url)
    if not source.url.get_backend_name().startswith("sqlite"):
        sys.exit(f"DATABASE_URL should be the SQLite database to copy from, not {source.url.get_backend_name()}")

    if "--check" not in sys.argv:
        tables = Base.metadata.sorted_tables
        with target.begin() as conn:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t.name}"' for t in tables) + " RESTART IDENTITY CASCADE"))
            with source.connect() as src:
                for table in tables:
                    rows = [dict(r._mapping) for r in src.execute(select(table))]
                    for i in range(0, len(rows), BATCH):
                        conn.execute(table.insert(), rows[i:i + BATCH])
                    if "id" in table.c and rows:
                        conn.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                                          f"(SELECT max(id) FROM \"{table.name}\"))"))
    before, after = counts(source), counts(target)
    differ = {name: (before[name], after[name]) for name in before if before[name] != after[name]}
    total = sum(before.values())
    print(f"{len(before)} tables, {total} rows in SQLite; " + ("all copied." if not differ else f"MISMATCH: {differ}"))
    sys.exit(1 if differ else 0)


if __name__ == "__main__":
    main()
