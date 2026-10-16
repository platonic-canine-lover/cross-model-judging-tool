# Testing a Copilot Studio agent

The `copilot-studio` adapter puts an agent you built in Microsoft Copilot
Studio through the same case set as any API model, and the panel grades its
answers. It uses the official Microsoft 365 Agents SDK client,
[`microsoft-agents-copilotstudio-client`](https://pypi.org/project/microsoft-agents-copilotstudio-client/).

**Status, 16 October 2026:** built against the documented client API and
unit-tested with a fake client (`tests/test_adapters.py`). It has not been
run against a live agent, because this repository's author had no tenant
to hand at the time. Everything below is the documented procedure; expect
to adjust the first time it meets a real tenant, and please record what
changed.

## One-time setup

1. **Publish the agent** in Copilot Studio. Note the **environment ID**
   (Power Platform admin centre, or the URL of the agent in the maker
   portal) and the agent's **schema name** (Settings → Advanced, often
   `cr123_myAgent`).
2. **Register an app in Entra ID** (Azure portal → App registrations → New).
   - Supported account types: this organisation only.
   - Platform: Mobile and desktop applications, redirect URI
     `http://localhost`, and allow public client flows (the adapter signs
     in with the device-code flow, so no client secret is stored).
   - API permissions: add **Power Platform API → CopilotStudio.Copilots.Invoke**
     (delegated) and grant admin consent. If the Power Platform API does not
     appear in the list, it has to be added to the tenant first (see
     Microsoft's "Power Platform API" documentation).
   - Note the **application (client) ID** and the **tenant ID**.
3. **Install the optional extra** and set the environment:

```bash
uv pip install -e ".[copilot]"
export COPILOTSTUDIOAGENT__ENVIRONMENTID=<environment id>
export COPILOTSTUDIOAGENT__AGENTAPPID=<app client id>
export COPILOTSTUDIOAGENT__TENANTID=<tenant id>
```

## Run

```bash
jury run --target copilot-studio:cr123_myAgent \
  --judge anthropic:claude-haiku-5-5 --judge openai:gpt-5-mini --judge ollama:qwen3.8:27b \
  --self-judge-as azure:<your-gpt-deployment>
```

The first call prints a device-code sign-in message; open the link, enter
the code, sign in as a user who can access the environment. MSAL caches the
token for the process.

`--self-judge-as` matters here: a Copilot Studio agent is built to do its
job, not to grade transcripts, so "the model judging itself" means the
model the agent runs on. Copilot Studio's generative answers run on Azure
OpenAI, so pointing at your Azure OpenAI deployment of the same model family
is the closest available equivalent. Say which you used in the write-up.

## What the adapter does differently, and why

- **No system prompt.** The agent's instructions were set when it was
  built. A case's `system` is ignored and counted (`ignored_system_prompts`),
  so every persona-override case tests the agent exactly as its builder
  shipped it. That is the point: the question is whether the deployed
  agent holds its persona, not whether the underlying model would with
  different instructions.
- **Server-side conversation state.** Each case opens a fresh conversation
  and drives the user turns in order; prior assistant turns in the case
  are not replayed (the agent has its own). Only the last reply is graded.
- **No token usage.** The client reports none, so usage stays `None` in the
  recording rather than being estimated. The report counts those answers
  as "no usage reported".
- **Topics and actions fire.** If the agent has topics with trigger phrases
  or actions that call external systems, the probes will hit them. Run
  against a test copy of the agent, not the production one.

## Reading the result

A deployed Copilot Studio agent typically has guardrails the builder did
not write, applied by the platform. A high pass rate on persona-override
is therefore expected and not very informative; the informative cases are
the ones where the panel fails it, and the instruction-following and
honesty categories, where platform guardrails do less. Read the
DISAGREEMENTS section first.
