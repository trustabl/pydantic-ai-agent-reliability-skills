# pydantic-ai-agent-reliability-skills

Trustabl Forge for [Pydantic AI](https://ai.pydantic.dev): give your agent a tool that generates a
pre-coding reliability skill (`SKILL.md`) for the repository it works in.

Forge reads the repository's dependency manifests (`pyproject.toml`, `requirements.txt`, `package.json`,
`go.mod` and others), finds the agent SDKs it uses, and builds a skill from Trustabl's detection rules for
exactly those SDKs: the Claude Agent SDK, OpenAI Agents SDK, Google ADK, MCP, LangChain and LangGraph,
CrewAI, Pydantic AI, the Vercel AI SDK, AutoGen and more. An agent that follows the skill applies the rules
while it writes code, instead of meeting them later as scan findings.

## Install

```bash
pip install pydantic-ai-agent-reliability-skills
```

Requires Python 3.10 or later and `pydantic-ai-slim` 2.0 or later.

## Use

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai_agent_reliability_skills import AgentReliabilitySkills

agent = Agent(
    'anthropic:claude-sonnet-5',
    capabilities=[
        LocalWorkspace('.'),
        AgentReliabilitySkills(),
    ],
)
```

The capability adds one tool, `generate_reliability_skill(path='.', policy=None, lang=None)`, which returns
the `SKILL.md` content, the SDKs it covers and the rules release it was built from. It writes nothing: its
instructions tell the agent to save the skill to `.claude/skills/trustabl-pre-coding/SKILL.md` with its own
file tools, and to replace an existing file there only if it carries a Forge stamp, never a hand-written one.

| Input | Meaning |
|---|---|
| `path` | Repository directory, relative to the workspace. |
| `policy` | SDK categories to add on top of the detected ones, for an SDK not yet in a manifest, such as `mcp`. |
| `lang` | Languages to add: `python`, `typescript`, `go`. |

| Option | Default | Meaning |
|---|---|---|
| `command` | `None` | Analyzer binary to run. `None` uses `trustabl` on the workspace's PATH, else the pinned release. |
| `engine_version` | `0.1.16` | Analyzer release to download. Must be `0.1.14` or later. |
| `timeout` | `300` | Seconds for one Forge run. The first run also downloads the rules. |
| `guidance` | `None` | Replaces the default instructions. `''` adds none. |

## How it runs

Forge is part of the open-source [Trustabl analyzer](https://github.com/trustabl/agent-reliability-analyzer).
The tool runs `trustabl forge` inside the agent's workspace. When no `trustabl` is on the workspace's PATH,
it downloads the pinned analyzer release, checks it against the release's `checksums.txt` (a mismatch is a
hard failure and nothing is executed) and caches it. Set `TRUSTABL_CACHE_DIR` to change where.

No model call and no API key. The first run fetches the analyzer and Trustabl's rules from GitHub; after that
both work from cache.

## Related

- [agent-reliability-skills](https://github.com/trustabl/agent-reliability-skills): the same Forge tool as an
  MCP server, for Claude Code, Cursor and other MCP clients.
- [pydantic-ai-trustabl](https://github.com/trustabl/pydantic-ai-tool): scan an agent repository for
  reliability and safety weaknesses from a Pydantic AI agent.

License: Apache-2.0.
