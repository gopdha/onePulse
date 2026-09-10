# Migration Plan Phase 5 — Python-only image. Reporting itself never
# touches Node or the ADO PAT (Phase 4's split) — it only spawns the
# PPTX-parsing MCP server (scripts/pptx_mcp_server.py), a plain Python
# subprocess, for Status Update Analysis.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Real Azure CLI — DefaultAzureCredential's AzureCliCredential fallback
# (Postgres, Foundry, Storage Queues). Phase 5 is still local, no Managed
# Identity yet (Phase 6) — real az login state comes from a shared named
# volume at /root/.azure, never baked into the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg lsb-release \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs/onepulse_common ./libs/onepulse_common
RUN pip install --no-cache-dir ./libs/onepulse_common

COPY trace_debug.py ./trace_debug.py
COPY scripts/pptx_mcp_server.py scripts/verify_migration.py ./scripts/

# Migration Plan Phase 7 bar-for-done: "verify_migration.py green against
# the real database from the deployed environment" — a real, literal
# requirement, not provable by running the same script from a laptop
# against the same database (that proves the database, not that this
# runs from deployed compute under the real app_role Managed Identity).
# Reporting is the natural host: it already has the full onepulse_common
# install, asyncpg, and the real app_role identity attached. Run via:
#   az containerapp exec -g onepulse-gr -n onepulse-reporting \
#     --command "python scripts/verify_migration.py --target dev"

# The real status decks Status Update Analysis reads — one per real
# registered program (reporting/main.py's STATUS_DECK_PATH_BY_PROJECT).
COPY sample_status_deck.pptx leave_tracker_status_deck.pptx aiobs_status_deck.pptx ./

COPY reporting ./reporting

# Real, ephemeral by design this phase — rendered .pptx output and full-
# fidelity logs both used to depend on local disk surviving a restart.
# Logs move to stdout this phase (see reporting/main.py); rendered-report
# persistence to durable storage (Blob Storage + SAS) is real, disclosed,
# not-yet-built Phase 7 work (ADR-021) — a container restart genuinely
# loses anything under output/ today, unchanged from before this phase.
RUN mkdir -p output

CMD ["python", "-m", "reporting.main"]
