"""Applies every migration in scripts/migrations/, in order, against a
real Azure Database for PostgreSQL Flexible Server instance — exactly
per DevOps Setup Section 2.1 and Build Plan Phase 2. Idempotent: every
statement in every migration file is written to be safely re-runnable
(CREATE TABLE IF NOT EXISTS, DROP POLICY IF EXISTS + CREATE POLICY,
naturally-idempotent GRANT/REVOKE).

A clean exit here is NOT evidence a migration actually applied — that's
exactly what verify_migration.py is for (DevOps Setup Section 2.1's own
framing: "a migration tool reporting success is not, by itself,
evidence a change actually took effect"). Always run verify_migration.py
after this, never treat this script's exit code alone as proof.

Connects using the same real Managed Identity / Entra ID pattern as
onepulse_common.db.PostgresClient — no static credential, ever.

Run: python scripts/migrate.py --target dev
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Only `dev` is real infrastructure today (onepulse-pg-dev). staging and
# production are listed in Physical Architecture Section 4 / DevOps
# Setup Section 4 as separate server instances that do not exist yet —
# adding them here before they're real would be exactly the kind of
# untested config this project's own conventions warn against.
TARGETS: dict[str, PostgresSettings] = {
    "dev": PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_PG_ROLE", "app_role_local_dev"),
    ),
}


async def apply_migrations(settings: PostgresSettings) -> None:
    client = await PostgresClient.connect(settings, min_size=1, max_size=2)
    try:
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            raise RuntimeError(f"No migration files found in {MIGRATIONS_DIR}")
        async with client.pool.acquire() as conn:
            for migration_file in migration_files:
                print(f"Applying {migration_file.name}...")
                sql = migration_file.read_text(encoding="utf-8")
                await conn.execute(sql)
                print(f"Applied {migration_file.name}")
    finally:
        await client.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=list(TARGETS))
    args = parser.parse_args()

    settings = TARGETS[args.target]
    print(f"Migrating target='{args.target}' host='{settings.host}' database='{settings.database}' "
          f"role='{settings.role_name}'")
    await apply_migrations(settings)
    print("\nAll migrations applied. Run verify_migration.py now — this exit code is not evidence by itself.")


if __name__ == "__main__":
    asyncio.run(main())
