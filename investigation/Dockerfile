# Migration Plan Phase 5 — the ONE image in this system carrying both
# Python and Node.js, and the only one with a real path to the ADO PAT.
# Expected to be substantially larger than every other image — that is
# correct, not a regression to optimize away this phase (see the
# Dockerfile's own real measured size in CLAUDE.md Task 44): it is the
# concrete cost of confining Node/the PAT/the MCP dependency surface to
# exactly one container, which is the entire point of Phase 4's split.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Real Azure CLI (Postgres/Foundry/Storage Queue auth) AND real Node.js
# 20.x (matching this project's own locally-proven v20.13.1) in one
# apt-get pass. Node exists ONLY in this image — see Runbook §2 for the
# live verification that confirms it's genuinely absent from the other
# three.
#
# Real, live-discovered gap (Migration Plan Phase 5, CLAUDE.md Task 44):
# `@azure-devops/mcp` transitively depends on `keytar` (native credential-
# storage bindings). It never surfaced locally — this project's own
# Windows dev machine has whatever keytar's Windows binding needs
# already present — but inside this minimal Debian-slim image, spawning
# the real MCP server crashed immediately with `Error: libsecret-1.so.0:
# cannot open shared object file`, before the MCP handshake could even
# complete (surfacing to Reporting as an opaque `mcp.shared.exceptions.
# MCPError: Connection closed` with no indication of the real cause —
# found only by exec'ing into the running container and spawning the
# server directly, not from the Dockerfile or any log this project
# already had). `libsecret-1-0` is the real runtime library `keytar`
# `dlopen`s on Linux; it is not needed at `npm ci` time (that step
# succeeds either way), only at real spawn time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg lsb-release libsecret-1-0 \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs/onepulse_common ./libs/onepulse_common
RUN pip install --no-cache-dir ./libs/onepulse_common

COPY trace_debug.py ./trace_debug.py

# The real fix Task 39 prepared and this phase finally gives a home to:
# @azure-devops/mcp installed via a real `npm ci` from the committed
# lockfile, at BUILD time — never resolved via `npx` at spawn time, which
# would require outbound network access at request time and has no
# recovery path inside a container if that fetch or its cache corrupts
# (the exact real incident that motivated pinning it locally at all).
COPY investigation/package.json investigation/package-lock.json ./investigation/
RUN cd investigation && npm ci --omit=dev

COPY investigation/investigate.py investigation/main.py investigation/store.py ./investigation/

EXPOSE 8200
CMD ["python", "-m", "uvicorn", "investigation.main:app", "--host", "0.0.0.0", "--port", "8200"]
