"""Forge toolset -- runs `trustabl forge` and returns the generated pre-coding skill."""

from __future__ import annotations

from pydantic import BaseModel

from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelRetry, ToolFailed, UserError
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import FunctionToolset, ToolsetTool
from pydantic_ai.workspaces import (
    SupportsCommands,
    Workspace,
    WorkspaceBackend,
    WorkspaceError,
    WorkspaceReadOnlyError,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
    WrapperWorkspace,
)

SKILL_DESTINATION = '.claude/skills/trustabl-pre-coding/SKILL.md'
"""Where a generated skill usually goes, relative to the repository."""

_NOT_FOUND_EXIT = 127
_ERROR_TAIL_CHARS = 2000
_NO_SDK = 'no SDKs detected'

_LAUNCHER = f'command -v "$1" > /dev/null 2>&1 || exit {_NOT_FOUND_EXIT}\nexec env "$@"'
"""Resolve the binary in the workspace, then exec it so the workspace timeout reaches it."""

_STAMP_PREFIX = '<!-- generated: '
_STAMP_SUFFIX = ' -->'


class ForgeStamp(BaseModel):
    """The provenance line Forge writes into every skill it generates."""

    date: str
    rules: str
    schema_version: int
    sdks: list[str]
    template: int = 1


class ReliabilitySkill(BaseModel):
    """A generated pre-coding reliability skill and what it was built from."""

    skill_md: str
    """The full SKILL.md content."""

    sdks: list[str] = []
    """Agent SDKs the skill covers, read from its Forge stamp."""

    rules_version: str = ''
    """Trustabl rules release the skill was generated from."""

    note: str = ''
    """Anything `trustabl forge` printed to stderr on success, such as a warning."""


def parse_stamp(content: str) -> ForgeStamp | None:
    """Read the Forge stamp, or `None` when the content has no well-formed one.

    Mirrors `ParseStamp` in the analyzer's `internal/forge/stamp.go`, so this
    package and `trustabl forge check` agree on what counts as a Forge-generated
    file. A stamp with no `template` field predates it and is version 1.
    """
    start = content.find(_STAMP_PREFIX)
    if start < 0:
        return None
    rest = content[start + len(_STAMP_PREFIX):]
    end = rest.find(_STAMP_SUFFIX)
    if end < 0:
        return None

    parts = rest[:end].split(' | ', 4)
    if len(parts) not in (4, 5):
        return None

    def field(part: str, name: str) -> str | None:
        prefix = f'{name}: '
        return part[len(prefix):] if part.startswith(prefix) else None

    rules = field(parts[1], 'rules')
    schema = field(parts[2], 'schema')
    sdks = field(parts[3], 'sdks')
    if rules is None or schema is None or sdks is None or not schema.lstrip('+-').isdigit():
        return None

    template = 1
    if len(parts) == 5:
        t = field(parts[4], 'template')
        if t is None or not t.lstrip('+-').isdigit() or int(t) < 1:
            return None
        template = int(t)

    return ForgeStamp(
        date=parts[0],
        rules=rules,
        schema_version=int(schema),
        sdks=[s.strip() for s in sdks.split(', ') if s.strip()],
        template=template,
    )


def parse_skill(stdout: str, stderr: str = '') -> ReliabilitySkill:
    """Turn a successful `trustabl forge` run into a `ReliabilitySkill`."""
    stamp = parse_stamp(stdout)
    return ReliabilitySkill(
        skill_md=stdout,
        sdks=stamp.sdks if stamp else [],
        rules_version=stamp.rules if stamp else '',
        note=stderr.strip(),
    )


def forge_args(command: str, path: str, policy: list[str] | None, lang: list[str] | None) -> list[str]:
    """Arguments for `trustabl forge`. The CLI owns the accepted values and their errors."""
    args = [command, 'forge', path]
    p = [v.strip() for v in policy or [] if v.strip()]
    if p:
        args += ['--policy', ','.join(p)]
    l = [v.strip() for v in lang or [] if v.strip()]
    if l:
        args += ['--lang', ','.join(l)]
    return args


def _innermost_backend(workspace: Workspace) -> WorkspaceBackend:
    """The backend under any facades and wrappers."""
    current: WorkspaceBackend = workspace
    while isinstance(current, Workspace):
        current = current.wrapped if isinstance(current, WrapperWorkspace) else current.backend
    return current


def supports_commands(workspace: Workspace) -> bool:
    """Whether `workspace.run` can succeed for this workspace."""
    if not workspace.attached or workspace.read_only:
        return False
    return isinstance(_innermost_backend(workspace), SupportsCommands)


def _raise_tool_failure(error: WorkspaceError) -> None:
    """Report a workspace refusal to the model; a retry cannot fix any of these."""
    if isinstance(error, WorkspaceUnavailableError):
        raise error
    if isinstance(error, WorkspaceReadOnlyError):
        raise ToolFailed('The workspace is read-only; Forge was refused.') from error
    raise ToolFailed(str(error) or f'The workspace operation failed ({type(error).__name__}).') from error


_INSTALL_HINT = (
    'The Trustabl analyzer, which runs Forge, is not available in this workspace.\n'
    'The pinned analyzer was downloaded and verified on the host, but this workspace '
    'cannot see that path, which is normal for a sandbox.\n'
    'Install it inside the workspace instead:\n'
    '    brew install trustabl/tap/trustabl\n'
    '    scoop bucket add trustabl https://github.com/trustabl/scoop-trustabl && scoop install trustabl\n'
    'or add the binary to the sandbox image.'
)


class AgentReliabilitySkillsToolset(FunctionToolset[AgentDepsT]):
    """Exposes one tool that generates a pre-coding reliability skill for the workspace repository.

    Forge runs in the run's workspace, so it reads the repository the agent is
    working in, local or sandboxed. Problems the model cannot fix -- no analyzer
    in the workspace, a run that failed -- raise `UserError`. A repository with
    no detected agent SDK raises `ModelRetry`, so the model can name the SDK with
    `policy` and call again. A timeout also raises `ModelRetry`.
    """

    def __init__(self, *, command: str | None, engine_version: str, timeout: float) -> None:
        super().__init__()
        self._command = command
        self._engine_version = engine_version
        self._timeout = timeout
        self.add_function(self.generate_reliability_skill, name='generate_reliability_skill')

    async def get_tools(self, ctx: RunContext[AgentDepsT]) -> dict[str, ToolsetTool[AgentDepsT]]:
        """Offer the tool only when the workspace can run commands."""
        if not supports_commands(ctx.workspace):
            return {}
        return await super().get_tools(ctx)

    async def _resolve_command(self, ctx: RunContext[AgentDepsT]) -> str:
        """Find an analyzer the workspace can actually execute.

        Prefers one already on the workspace's PATH. Falls back to the pinned
        release, downloaded and checksum-verified on the host, but only after
        confirming the workspace can see that path -- a host download is
        invisible to a sandbox.
        """
        if self._command is not None:
            return self._command

        probe = await ctx.workspace.run(['sh', '-c', 'command -v trustabl'], timeout=30)
        if probe.exit_code == 0 and probe.stdout.strip():
            return 'trustabl'

        from pydantic_ai_agent_reliability_skills._binary import ensure_binary

        path = str(ensure_binary(self._engine_version))
        visible = await ctx.workspace.run(['sh', '-c', 'test -x "$1"', 'sh', path], timeout=30)
        if visible.exit_code != 0:
            raise UserError(_INSTALL_HINT)
        return path

    async def generate_reliability_skill(
        self,
        ctx: RunContext[AgentDepsT],
        path: str = '.',
        policy: list[str] | None = None,
        lang: list[str] | None = None,
    ) -> ReliabilitySkill:
        """Generate a pre-coding reliability skill (SKILL.md) for a repository with Trustabl Forge.

        Forge reads the repository's dependency manifests, finds the agent SDKs it
        uses, and builds the skill from Trustabl's detection rules for exactly
        those SDKs, so the rules are applied while code is written.

        Args:
            ctx: the current agent run context.
            path: repository directory, relative to the workspace working directory.
            policy: SDK categories to add on top of the detected ones, for an SDK not
                yet declared in a manifest, such as `mcp` or `openai_sdk`.
            lang: languages to add on top of the detected ones: `python`,
                `typescript`, `go`.

        Returns:
            The SKILL.md content, the SDKs it covers and the rules release it was
            built from. Nothing is written; save it with your file tools, usually
            to `.claude/skills/trustabl-pre-coding/SKILL.md`.
        """
        command = await self._resolve_command(ctx)
        args = forge_args(command, path, policy, lang)
        try:
            result = await ctx.workspace.run(['sh', '-c', _LAUNCHER, 'sh', *args], timeout=self._timeout)
        except WorkspaceTimeoutError:
            raise ModelRetry(
                f'trustabl forge did not finish within {self._timeout}s. The first run also '
                'downloads the rules; try again.'
            ) from None
        except WorkspaceError as e:
            _raise_tool_failure(e)

        if result.exit_code == 0:
            return parse_skill(result.stdout, result.stderr)

        tail = f'{result.stdout}\n{result.stderr}'.strip()[-_ERROR_TAIL_CHARS:]
        if result.exit_code == _NOT_FOUND_EXIT and not result.stdout.strip():
            raise UserError(_INSTALL_HINT)
        if result.exit_code == 1 and _NO_SDK in result.stderr:
            raise ModelRetry(
                'Forge found no supported agent SDK in this repository\'s dependency manifests. '
                'If the repository does use one, for example one declared only in a subfolder\'s '
                'manifest, call generate_reliability_skill again with `policy` naming it, '
                f'such as ["mcp"].\n\ntrustabl forge said:\n{tail}'
            )
        raise UserError(f'trustabl forge exited with code {result.exit_code}.\n\nOutput:\n{tail}')
