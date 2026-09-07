"""Phase 0 / Task 3 go/no-go checkpoint: Foundry Agent Service.

Not a build phase deliverable — a standalone connectivity spike to answer
one question before Phase 3 (agentic, tool-using services) is designed:
does AIProjectClient + Foundry Agent Service work at all against this
project's real Foundry resource, authenticated the same way as everything
else here (DefaultAzureCredential, no static keys)?

Deliberately minimal: no tools, no custom instructions beyond a trivial
system prompt, one throwaway agent/thread/run. This is a different SDK
surface than onepulse_common/foundry.py (which wraps the plain Messages
API via AnthropicFoundry) — see that module's scope note.

Run: python scripts/foundry_agent_spike.py

Real finding from running this (kept here, not silently worked around):
azure-ai-projects 2.6.0's `AIProjectClient.agents` is NOT the classic
thread/message/run Assistants-style surface this spike needs — that
package version ships a newer "Agent resource" model (create_version,
sessions, Hosted Agents) with no threads/messages/runs at all. The
classic surface (create_agent, threads, messages, runs.create_and_process)
lives on `azure.ai.agents.AgentsClient`, constructed directly against the
project endpoint rather than obtained via AIProjectClient.agents.
"""

from __future__ import annotations

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import ListSortOrder
from azure.identity import DefaultAzureCredential

from onepulse_common.agent_cleanup import maybe_delete_agent

PROJECT_ENDPOINT = "https://onepulse-resource.services.ai.azure.com/api/projects/onepulse"
DEPLOYMENT_NAME = "onePulse-gpt-5-mini"


def main() -> None:
    credential = DefaultAzureCredential()
    agents_client = AgentsClient(endpoint=PROJECT_ENDPOINT, credential=credential)

    with agents_client:
        agent = agents_client.create_agent(
            model=DEPLOYMENT_NAME,
            name="onepulse-spike-agent",
            instructions="You are a helpful assistant.",
        )
        print(f"Created agent: {agent.id}")

        thread = agents_client.threads.create()
        print(f"Created thread: {thread.id}")

        message = agents_client.messages.create(
            thread_id=thread.id,
            role="user",
            content="Say 'OnePulse Foundry Agent Service connectivity check: OK' and nothing else.",
        )
        print(f"Created message: {message.id}")

        run = agents_client.runs.create_and_process(
            thread_id=thread.id,
            agent_id=agent.id,
        )
        print(f"Run status: {run.status}")

        if run.status == "failed":
            print(f"Run failed: {run.last_error}")
        else:
            messages = agents_client.messages.list(
                thread_id=thread.id,
                order=ListSortOrder.ASCENDING,
            )
            print("\n--- Thread messages ---")
            for msg in messages:
                if msg.text_messages:
                    last_text = msg.text_messages[-1].text.value
                    print(f"[{msg.role}] {last_text}")

        maybe_delete_agent(agents_client, agent.id, label=agent.name)


if __name__ == "__main__":
    main()
