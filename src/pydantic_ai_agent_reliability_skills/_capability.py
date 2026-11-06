"""Agent Reliability Skills capability (Trustabl Forge)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import UserError
from pydantic_ai.tools import AgentDepsT, RunContext

from pydantic_ai_agent_reliability_skills._toolset import SKILL_DESTINATION, AgentReliabilitySkillsToolset

_FORGE_INSTRUCTIONS = (
    'Before writing agent code, call `generate_reliability_skill` for the repository. It returns '
    'a SKILL.md built from Trustabl\'s detection rules for the agent SDKs the repository uses. '
    f'Save it to `{SKILL_DESTINATION}` with your file tools, but replace an existing file there '
    'only if it starts with a Forge stamp (`<!-- generated: `); never overwrite a hand-written '
    'skill. Then follow the skill\'s rules while you write code. If no SDK is detected, call it '
    'again with `policy` naming the SDK you are using.'
)

_ENGINE_VERSION = '0.1.15'


@dataclass
class AgentReliabilitySkills(AbstractCapability[AgentDepsT]):
    """Generates a pre-coding reliability skill for the workspace repository with Trustabl Forge.

    Adds a `generate_reliability_skill` tool that runs `trustabl forge` in the
    run's workspace and returns the SKILL.md, so the agent applies Trustabl's
    rules for the repository's agent SDKs while it writes code, instead of
    meeting them later as scan findings. The capability writes nothing; the
    agent saves the skill with its own file tools.

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

    The analyzer is resolved from the workspace's PATH when present; otherwise the
    pinned release is downloaded and verified against the release's
    `checksums.txt` before anything is executed.
    """

    command: str | None = None
    """Name or path of the analyzer binary. `None` resolves it automatically."""

    engine_version: str = _ENGINE_VERSION
    """Analyzer release to download when none is on the workspace's PATH.

    Pinned rather than tracking latest, so checksum verification stays meaningful
    and a bad analyzer release cannot reach every user at once. Forge's `--lang`
    flag needs 0.1.14 or later."""

    timeout: float = 300.0
    """Maximum seconds for one Forge run. The first run also downloads the rules."""

    guidance: str | None = None
    """Replaces the default instructions. `''` contributes none."""

    async def before_run(self, ctx: RunContext[AgentDepsT]) -> None:
        """Fail at the start of a run that has no workspace to read."""
        if not ctx.workspace.attached:
            raise UserError(
                'AgentReliabilitySkills needs a workspace. Add one to the agent, for example '
                "`LocalWorkspace('.')`."
            )

    def get_toolset(self) -> AgentReliabilitySkillsToolset[AgentDepsT]:
        """Build the toolset providing `generate_reliability_skill`."""
        return AgentReliabilitySkillsToolset[AgentDepsT](
            command=self.command,
            engine_version=self.engine_version,
            timeout=self.timeout,
        )

    def get_instructions(self) -> str | None:
        """Generate-save-follow guidance, unless `guidance` overrides it."""
        if self.guidance is not None:
            return self.guidance or None
        return _FORGE_INSTRUCTIONS

    @classmethod
    def get_serialization_name(cls) -> str:
        """Name this capability answers to in an agent spec."""
        return 'AgentReliabilitySkills'
