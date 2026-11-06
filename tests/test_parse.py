"""Stamp parsing and argument building are the non-trivial logic here, so they are what gets tested."""

from pydantic_ai_agent_reliability_skills import forge_args, parse_skill, parse_stamp

STAMP_V2 = '<!-- generated: 2026-11-06 | rules: v0.7.0 | schema: 3 | sdks: claude_sdk, mcp | template: 2 -->'
STAMP_V1 = '<!-- generated: 2026-10-01 | rules: v0.6.0 | schema: 2 | sdks: openai_sdk -->'


def test_stamp_with_template_field():
    s = parse_stamp(f'---\nname: trustabl-pre-coding\n---\n{STAMP_V2}\n# Rules\n')
    assert s is not None
    assert s.date == '2026-11-06'
    assert s.rules == 'v0.7.0'
    assert s.schema_version == 3
    assert s.sdks == ['claude_sdk', 'mcp']
    assert s.template == 2


def test_stamp_without_template_field_is_version_1():
    s = parse_stamp(STAMP_V1)
    assert s is not None
    assert s.template == 1
    assert s.sdks == ['openai_sdk']


def test_hand_written_file_has_no_stamp():
    """The overwrite rule depends on this: no stamp means not Forge's file."""
    assert parse_stamp('# My own skill\nDo things carefully.\n') is None


def test_malformed_stamps_are_rejected():
    assert parse_stamp('<!-- generated: 2026-11-06 | rules: v1 | schema: x | sdks: mcp -->') is None
    assert parse_stamp('<!-- generated: 2026-11-06 | rules: v1 -->') is None
    assert parse_stamp('<!-- generated: 2026-11-06 | rules: v1 | schema: 3 | sdks: mcp | template: 0 -->') is None
    assert parse_stamp('<!-- generated: 2026-11-06 | rules: v1 | schema: 3 | sdks: mcp') is None


def test_parse_skill_reads_sdks_and_rules():
    out = parse_skill(f'{STAMP_V2}\n# Rules\n', stderr='  note: rules cache refreshed \n')
    assert out.sdks == ['claude_sdk', 'mcp']
    assert out.rules_version == 'v0.7.0'
    assert out.note == 'note: rules cache refreshed'
    assert out.skill_md.startswith(STAMP_V2)


def test_parse_skill_without_stamp_keeps_content():
    out = parse_skill('# no stamp\n')
    assert out.sdks == []
    assert out.rules_version == ''
    assert out.skill_md == '# no stamp\n'


def test_forge_args_join_and_drop_blanks():
    assert forge_args('trustabl', '.', None, None) == ['trustabl', 'forge', '.']
    assert forge_args('trustabl', 'repo', [' mcp ', '', 'openai_sdk'], ['python']) == [
        'trustabl', 'forge', 'repo', '--policy', 'mcp,openai_sdk', '--lang', 'python',
    ]
