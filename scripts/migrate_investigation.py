"""Applies every migration in scripts/investigation_migrations/, in
order, against the real Investigation schema — the companion to
scripts/migrate.py, deliberately separate rather than a --schema flag on
the same script.

Real, load-bearing reason for the separate script, not just a naming
preference: this connects as investigation_role/investigation_role_local_dev,
never as app_role/app_role_local_dev. Running `CREATE SCHEMA investigation`
under the Reporting role would make the Reporting role the schema's
OWNER — Postgres ownership grants full access regardless of any
GRANT/REVOKE placed on top afterward, silently defeating the entire
Migration Plan Phase 4 boundary this schema exists to enforce (see
scripts/investigation_migrations/0001_initial_schema.sql's own header
for the real mistake this project made and fixed once already). Having
the Investigation role create (and therefore own) its own schema from
the first statement avoids that trap structurally, rather than needing
a manual ownership-transfer cleanup after the fact.

A clean exit here is NOT evidence a migration actually applied — same
standing rule as migrate.py. Run scripts/verify_migration.py after,
which checks both this schema and the mirror boundary (the Reporting
role's own real, structural lack of access to it).

Run: python scripts/migrate_investigation.py --target dev
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

MIGRATIONS_DIR = Path(__file__).parent / "investigation_migrations"

TARGETS: dict[str, PostgresSettings] = {
    # Real decision (Migration Plan Phase 6, mirroring migrate.py's own
    # ADR-023 fix exactly): connects as investigation_role, not
    # investigation_role_local_dev, by default. Same root cause this
    # would otherwise repeat — whichever role runs a migration becomes
    # the owner of anything it creates — confirmed live for this exact
    # schema during Phase 6's own bootstrap: investigation_role picked
    # up unintended owner-implicit DELETE/TRUNCATE/REFERENCES/TRIGGER/
    # MAINTAIN on investigation_runs the moment ownership transferred,
    # fixed by 0002_reassert_investigation_grants.sql. A fresh migration
    # run under this new default never hits that gap in the first place.
    "dev": PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=os.environ.get("ONEPULSE_INVESTIGATION_PG_ROLE", "investigation_role"),
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
    print(f"Migrating (investigation schema) target='{args.target}' host='{settings.host}' "
          f"database='{settings.database}' role='{settings.role_name}'")
    await apply_migrations(settings)
    print("\nAll investigation migrations applied. Run verify_migration.py now — this exit code is not evidence by itself.")


if __name__ == "__main__":
    asyncio.run(main())
