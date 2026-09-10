# Migration Plan Phase 5 — Python-only image. No Node, no ADO PAT reachable
# from here (the whole point of Phase 4's split, verified inside this
# running container, not assumed from this file alone).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Real Azure CLI — for DefaultAzureCredential's AzureCliCredential
# fallback. Phase 5 is still local, no Managed Identity yet (Phase 6) —
# real az login state is provided at runtime via a shared named volume
# mounted at /root/.azure (see docker-compose.yml and the Runbook), never
# baked into the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg lsb-release \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs/onepulse_common ./libs/onepulse_common
RUN pip install --no-cache-dir ./libs/onepulse_common

COPY trace_debug.py ./trace_debug.py
COPY core_api ./core_api

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "core_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
