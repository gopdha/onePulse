"""Real rendered-report download by user-delegation SAS (ADR-021,
built for real in Migration Plan Phase 8/ADR-027 — the Blob-Storage half
of ADR-021 was designed then but never implemented; Phase 8's own bar
for done (a visitor cannot retrieve a SAS for a report outside its
scope) is what finally required building it).

Real, deliberately scoped decision, not a full pipeline migration: this
module does not change how `reporting` renders or persists a `.pptx`
today — every existing report keeps its real local/`file://`
`rendered_artifact_uri`, untouched. `rendered_artifact_uri` now may also
hold a `blob://<container>/<blob_name>` URI; only reports that actually
have one can be downloaded via `issue_download_sas`. Migrating the real
rendering pipeline onto Blob Storage end to end (removing the `file://`
path entirely) is real, disclosed, not-yet-done follow-up work — this
phase needed a real, working SAS mechanism to prove tenant isolation
against, not a full storage migration.

Same real Azure Storage account Storage Queues already use
(`onepulsequeuesdev`, ADR-019) — the natural home ADR-021 itself already
named for this. A user-delegation SAS is signed by a Managed Identity's
own delegation key, never a storage account key — `allowSharedKeyAccess`
stays `false` on this account, unaffected by this module.
"""

from __future__ import annotations

import datetime as dt

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobSasPermissions, generate_blob_sas
from azure.storage.blob.aio import BlobServiceClient

BLOB_ACCOUNT_URL = "https://onepulsequeuesdev.blob.core.windows.net"
REPORTS_CONTAINER = "reports"
BLOB_URI_SCHEME = "blob://"

# ADR-021's own stated constraint: "Once issued, a SAS URL is a bearer
# credential. Expiry must be short (minutes)."
DEFAULT_SAS_TTL_MINUTES = 5


def blob_uri(blob_name: str, container: str = REPORTS_CONTAINER) -> str:
    """The real, stable `rendered_artifact_uri` shape this module
    writes and reads: `blob://<container>/<blob_name>`.
    """
    return f"{BLOB_URI_SCHEME}{container}/{blob_name}"


def parse_blob_uri(uri: str) -> tuple[str, str] | None:
    """Returns (container, blob_name) for a real `blob://...` URI, or
    `None` for anything else (a legacy `file://` URI, most commonly) —
    the caller's real signal for "this report has no SAS-downloadable
    artifact," not an error.
    """
    if not uri.startswith(BLOB_URI_SCHEME):
        return None
    rest = uri.removeprefix(BLOB_URI_SCHEME)
    container, _, blob_name = rest.partition("/")
    if not container or not blob_name:
        return None
    return container, blob_name


async def upload_report_blob(
    credential: DefaultAzureCredential, blob_name: str, data: bytes, container: str = REPORTS_CONTAINER
) -> str:
    """Real upload via Managed Identity — no account key. Returns the
    real `blob://` URI to store in `reports.rendered_artifact_uri`.
    """
    async with BlobServiceClient(account_url=BLOB_ACCOUNT_URL, credential=credential) as service_client:
        container_client = service_client.get_container_client(container)
        await container_client.upload_blob(name=blob_name, data=data, overwrite=True)
    return blob_uri(blob_name, container)


async def issue_download_sas(
    credential: DefaultAzureCredential,
    container: str,
    blob_name: str,
    ttl_minutes: int = DEFAULT_SAS_TTL_MINUTES,
) -> str:
    """Real, short-lived user-delegation SAS (ADR-021) — signed by this
    identity's own delegation key (`get_user_delegation_key`, requires
    real `Storage Blob Delegator` RBAC), never a storage account key.

    Deliberately takes no authorization parameters — the caller (a real
    `core_api` route) must complete its own real authorization check
    (RLS tenant scope + program-level `actor_scope`) BEFORE calling this,
    per ADR-021's own stated constraint: "authorisation must happen
    before issuance." This function's only job is to mint the real SAS
    for a blob the caller has already decided is authorized.
    """
    now = dt.datetime.now(dt.timezone.utc)
    expiry = now + dt.timedelta(minutes=ttl_minutes)

    async with BlobServiceClient(account_url=BLOB_ACCOUNT_URL, credential=credential) as service_client:
        delegation_key = await service_client.get_user_delegation_key(
            key_start_time=now - dt.timedelta(minutes=1), key_expiry_time=expiry
        )

    sas_token = generate_blob_sas(
        account_name="onepulsequeuesdev",
        container_name=container,
        blob_name=blob_name,
        user_delegation_key=delegation_key,
        permission=BlobSasPermissions(read=True),
        expiry=expiry,
        start=now - dt.timedelta(minutes=1),
    )
    return f"{BLOB_ACCOUNT_URL}/{container}/{blob_name}?{sas_token}"
