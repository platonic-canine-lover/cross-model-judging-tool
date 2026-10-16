"""A published Microsoft Copilot Studio agent as the system under test.

Uses the official Microsoft 365 Agents SDK client
(`microsoft-agents-copilotstudio-client`, optional extra `copilot`). The agent
is addressed as `copilot-studio:<agent schema name>`; the environment supplies

    COPILOTSTUDIOAGENT__ENVIRONMENTID   Power Platform environment ID
    COPILOTSTUDIOAGENT__AGENTAPPID      Entra app registration (client) ID
    COPILOTSTUDIOAGENT__TENANTID        Entra tenant ID

See docs/copilot-studio.md for the one-time setup (app registration, API
permission, publishing the agent).

Differences from the API adapters, which the harness has to live with:

  * There is no system prompt: the agent's instructions were set when it was
    built. A case's `system` is therefore ignored and the fact is recorded,
    so a persona-override case tests the agent as its builder shipped it.
  * The agent holds conversation state server-side, so each case starts a
    fresh conversation and sends the turns in order; only the last reply is
    graded.
  * No token usage is reported. Usage stays None rather than being guessed.

Status: built against the documented client API and unit-tested with a
fake; not yet run against a live agent (no tenant to hand). The README says
so. Interactive sign-in via MSAL's public-client device-code flow is used
because the sample's `acquire_token` helper is not part of the package.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from jury.adapters.base import env, register
from jury.types import Message, Reply, Target, Usage


class _CopilotClientLike(Protocol):
    def start_conversation(self, emit_start_message: bool = ...) -> AsyncIterator[Any]: ...
    def ask_question(self, question: str, conversation_id: str) -> AsyncIterator[Any]: ...


class CopilotStudioTarget:
    def __init__(self, agent_schema_name: str, client: _CopilotClientLike | None = None) -> None:
        self.id = f"copilot-studio:{agent_schema_name}"
        self.agent = agent_schema_name
        self.ignored_system_prompts = 0
        self._client = client or self._build_client()

    def _build_client(self) -> _CopilotClientLike:
        try:
            from microsoft_agents.copilotstudio.client import ConnectionSettings, CopilotClient, PowerPlatformEnvironment
        except ImportError as e:  # pragma: no cover - exercised only without the extra installed
            raise RuntimeError('copilot-studio: install the optional extra: uv pip install -e ".[copilot]"') from e
        import msal

        settings = ConnectionSettings(
            environment_id=env("COPILOTSTUDIOAGENT__ENVIRONMENTID", provider="copilot-studio"),
            agent_identifier=self.agent,
            cloud=None,
            copilot_agent_type=None,
            custom_power_platform_cloud=None,
        )
        app_id = env("COPILOTSTUDIOAGENT__AGENTAPPID", provider="copilot-studio")
        tenant = env("COPILOTSTUDIOAGENT__TENANTID", provider="copilot-studio")
        audience = PowerPlatformEnvironment.get_token_audience(settings)
        app = msal.PublicClientApplication(app_id, authority=f"https://login.microsoftonline.com/{tenant}")
        accounts = app.get_accounts()
        result = app.acquire_token_silent([audience], account=accounts[0]) if accounts else None
        if not result:
            flow = app.initiate_device_flow(scopes=[audience])
            print(flow["message"])
            result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"copilot-studio: sign-in failed: {result.get('error_description', result)}")
        return CopilotClient(settings, result["access_token"])  # type: ignore[no-any-return]

    async def ask(self, messages: list[Message]) -> Reply:
        self.ignored_system_prompts += sum(1 for m in messages if m.role == "system")
        conversation_id: str | None = None
        async for activity in self._client.start_conversation(True):
            conv = getattr(activity, "conversation", None)
            if conv is not None and getattr(conv, "id", None):
                conversation_id = conv.id
        if conversation_id is None:
            raise RuntimeError("copilot-studio: start_conversation returned no conversation id")
        last_text = ""
        last_raw: dict[str, object] | None = None
        for m in messages:
            if m.role != "user":
                continue  # prior assistant turns live in the agent's own state; we only drive user turns
            texts: list[str] = []
            async for reply in self._client.ask_question(m.content, conversation_id):
                if getattr(reply, "type", None) == "message" and getattr(reply, "text", None):
                    texts.append(reply.text)
                    last_raw = {"type": reply.type, "text": reply.text}
            last_text = "\n".join(texts)
            await asyncio.sleep(0)
        return Reply(text=last_text, model=self.id, usage=Usage(), raw=last_raw)


@register("copilot-studio")
def _factory(agent: str, temperature: float | None) -> Target:
    """Sampling is fixed in the agent's build; a requested temperature is refused rather than silently ignored."""
    if temperature is not None:
        raise ValueError(
            "copilot-studio: temperature is set in the agent's configuration, not per call; omit --temperature for this target"
        )
    return CopilotStudioTarget(agent)
