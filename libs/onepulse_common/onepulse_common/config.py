"""Environment-variable-only configuration loading.

No secret values are ever read here, because there are none to read:
Postgres and Foundry both authenticate via Microsoft Entra ID through
DefaultAzureCredential (see db.py, foundry.py), so there is no password
or API key for this module to load, locally or in AKS.

In AKS, the non-secret values below come from a ConfigMap. Locally,
export them directly in the shell, or use a `.env.local` file (that
name is *not* covered by the `.env.*` gitignore exception for
`.env.example`, so double-check `git status` before committing if you
ever add one — it should never contain anything but hostnames).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is not set."""


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingConfigError(f"Required environment variable {name!r} is not set")
    return value


@dataclass(frozen=True)
class PostgresSettings:
    host: str
    database: str
    role_name: str
    port: int = 5432


@dataclass(frozen=True)
class FoundrySettings:
    base_url: str
    deployment_name: str


@dataclass(frozen=True)
class Settings:
    environment: str
    postgres: PostgresSettings
    foundry: FoundrySettings

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            environment=_required("ONEPULSE_ENVIRONMENT"),
            postgres=PostgresSettings(
                host=_required("ONEPULSE_PG_HOST"),
                database=_required("ONEPULSE_PG_DATABASE"),
                role_name=_required("ONEPULSE_PG_ROLE"),
                port=int(os.environ.get("ONEPULSE_PG_PORT", "5432")),
            ),
            foundry=FoundrySettings(
                base_url=_required("ONEPULSE_FOUNDRY_BASE_URL"),
                deployment_name=_required("ONEPULSE_FOUNDRY_DEPLOYMENT_NAME"),
            ),
        )
