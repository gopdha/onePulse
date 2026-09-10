"""Real answer to "how do migrations run under a workload identity"
(Migration Plan Phase 6, CLAUDE.md Task 45).

`migrate.py`/`migrate_investigation.py` both now default to the real
production role (`app_role`/`investigation_role`, ADR-023) — and both
roles are mapped via `pgaadauth_create_principal_with_oid` to a real
Managed Identity's object ID, which means (confirmed live, not assumed)
NO interactive session can authenticate as either:

    InvalidAuthorizationSpecificationError: Service principals cannot
    generate AAD_AUTH_TOKENTYPE_APP_USER tokens for role "app_role".

This is correct, not a bug — it's the whole reason these roles exist
separately from the local-dev ones. It means `migrate.py --target dev`
cannot be run by a human from their own machine once its default role
is the production one, for the same reason `az login` itself never
could impersonate it.

THE REAL MODEL, for the two eras this project actually has:

- **Before a real deployed workload exists carrying these identities**
  (today, and through Phase 6): ownership-establishing and grant-
  reasserting migrations — the ones that must run AS app_role/
  investigation_role specifically so the objects they touch are owned
  correctly from the start — are applied by a human holding the real
  Postgres Entra Administrator role, directly, using this script. This
  is not a workaround: it's the same real actor and pattern already
  used for `create_app_role.sql`/`create_investigation_role.sql`
  themselves (both scripts' own header comments: "run once per
  environment, manually, by a human holding the Microsoft Entra
  Administrator role"). Schema-owning migrations are now the same
  category of action as bootstrapping the role that owns them.

- **Once a real deployed workload exists** (Phase 7+): the correct
  operational model is a migration STEP as part of deployment (a
  Container Apps Job, or a one-off init task) that itself carries the
  target environment's real app_role/investigation_role Managed
  Identity — at that point `migrate.py`/`migrate_investigation.py`,
  unchanged, connect successfully via real IMDS-backed MI auth, and run
  exactly as designed. No human runs them interactively ever again in
  that world, which is a real improvement over today: a migration run
  by a human is exactly how this project got the ADR-023 ownership-
  drift bug in the first place (whichever role happens to run
  migrate.py becomes the owner) — removing the human from the loop
  removes that whole failure mode, not just works around it once.

For LOCAL, day-to-day schema work that does NOT need to establish
ownership (adding a column, a check constraint, a normal GRANT that
isn't reasserting ownership) — `migrate.py --target dev` with
`ONEPULSE_PG_ROLE=app_role_local_dev` (or `migrate_investigation.py`
with `ONEPULSE_INVESTIGATION_PG_ROLE=investigation_role_local_dev`)
remains the right, normal, human-runnable path — local dev's role
genuinely mirrors the production one's grants now (this same task's own
audit confirmed it), so this stays real evidence about what the
deployed workload can do, not a separate, drifting path.

Usage:
  python scripts/apply_admin_migration.py scripts/migrations/000X_....sql
  python scripts/apply_admin_migration.py scripts/investigation_migrations/000X_....sql
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from onepulse_common.config import PostgresSettings
from onepulse_common.db import PostgresClient

load_dotenv()

# The real Postgres Entra Administrator on onepulse-pg-dev — the one
# identity in this project that can ALTER OWNER TO either app_role or
# investigation_role, since neither the local-dev roles nor the
# production roles themselves can hand off ownership to a role they are
# not already a member of.
ADMIN_ROLE_NAME = "gopi@gopdhagmail.onmicrosoft.com"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_file", type=Path)
    args = parser.parse_args()

    if not args.migration_file.exists():
        raise SystemExit(f"No such file: {args.migration_file}")

    settings = PostgresSettings(
        host="onepulse-pg-dev.postgres.database.azure.com",
        database="onepulse",
        role_name=ADMIN_ROLE_NAME,
    )
    client = await PostgresClient.connect(settings, min_size=1, max_size=1)
    try:
        async with client.pool.acquire() as conn:
            sql = args.migration_file.read_text(encoding="utf-8")
            print(f"Applying {args.migration_file} as {ADMIN_ROLE_NAME}...")
            await conn.execute(sql)
            print(f"Applied {args.migration_file} successfully.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
