# Migration Plan Phase 5 — Python-only image. No Node, no ADO PAT, and no
# database/search/Foundry client of any kind (Phase 2's own structural
# no-data-access guarantee, unaffected by containerization).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

# Real Azure CLI — for DefaultAzureCredential's AzureCliCredential
# fallback (the token the BFF presents to the core API). Phase 5 is still
# local, no Managed Identity yet (Phase 6) — real az login state comes
# from a shared named volume at /root/.azure, never baked into the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg lsb-release \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY libs/onepulse_common ./libs/onepulse_common
RUN pip install --no-cache-dir ./libs/onepulse_common

COPY trace_debug.py ./trace_debug.py
COPY bff ./bff

EXPOSE 8100
CMD ["python", "-m", "uvicorn", "bff.main:app", "--host", "0.0.0.0", "--port", "8100"]
