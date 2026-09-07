"""Real embedding client for the Chat Assistant's Retrieval Index
(Physical Architecture Section 4: "Embeddings generated via a
Foundry-hosted embedding model, matching the same model/auth path as
every other AI component").

Real findings, checked live 2026-09-06, not assumed from the 11.x/1.x
generation of these SDKs this project has used elsewhere:

- `azure-ai-inference`'s `EmbeddingsClient` against this Foundry
  resource's unified `.services.ai.azure.com` inference route returns a
  real, live 404 for this deployment — that route does not serve this
  particular embedding deployment on this resource.
- The classic Azure OpenAI REST shape
  (`<resource>.openai.azure.com/openai/deployments/<deployment>/embeddings`)
  DOES work, confirmed with a real 200 response and a real 1536-dim
  vector. The `openai` SDK's `AzureOpenAI`/`AsyncAzureOpenAI` client
  targets exactly this shape and accepts `azure_ad_token_provider` — no
  static API key anywhere, matching convention #4, via the same
  `DefaultAzureCredential` every other client in this project already
  uses. `get_bearer_token_provider` was confirmed live for both the sync
  and async credential variants.

The real deployment itself (`onePulse-text-embedding-3-small`, model
`text-embedding-3-small`, GlobalStandard, capacity 10) was created for
this task — no embedding model existed on `onepulse-resource` before.
"""

from __future__ import annotations

from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

# The real, confirmed-working endpoint for this resource's embedding
# deployment — NOT the `.services.ai.azure.com` unified inference route,
# which 404s here (see module docstring).
FOUNDRY_OPENAI_ENDPOINT = "https://onepulse-resource.openai.azure.com/"

# Confirmed via `az cognitiveservices account show`: this is the scope
# Postgres-style token minting would use if Postgres were a Cognitive
# Services resource — here it genuinely is one, so this is the real
# resource-specific scope, not reused from db.py's unrelated
# ossrdbms-aad scope.
COGNITIVE_SERVICES_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"

EMBEDDING_DEPLOYMENT_NAME = "onePulse-text-embedding-3-small"
EMBEDDING_API_VERSION = "2024-06-01"

# text-embedding-3-small's real default output dimensionality — confirmed
# live via a real embed call, not assumed from the model name.
EMBEDDING_DIMENSIONS = 1536


def build_embedding_client(credential: DefaultAzureCredential) -> AsyncAzureOpenAI:
    """Builds a real, Entra-ID-authenticated async embeddings client.
    Caller owns `credential`'s lifecycle (same pattern as
    `PostgresClient.connect`) — this function does not close it.
    """
    token_provider = get_bearer_token_provider(credential, COGNITIVE_SERVICES_TOKEN_SCOPE)
    return AsyncAzureOpenAI(
        azure_endpoint=FOUNDRY_OPENAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version=EMBEDDING_API_VERSION,
    )


async def embed_texts(client: AsyncAzureOpenAI, texts: list[str]) -> list[list[float]]:
    """Real batch embedding call. Order of returned vectors matches the
    order of `texts` (the real API's own documented guarantee).
    """
    response = await client.embeddings.create(model=EMBEDDING_DEPLOYMENT_NAME, input=texts)
    return [item.embedding for item in response.data]
