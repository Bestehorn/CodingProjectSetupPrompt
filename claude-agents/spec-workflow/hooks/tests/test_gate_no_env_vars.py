"""The no-env-vars gate (gate_no_env_vars): 0 = allow the command, 2 = block it.

A corpus-style suite in both directions. The gate runs on EVERY shell command, so the two directions are
asymmetric exactly as for the push gate: an over-blocked read, search or scoped-temp prefix gets the hook
deleted, while a missed setter leaks a profile or a token across every project on the machine. The block arms
pin the forms measured as bypasses of the original setter-only gate (the per-command prefix `AWS_PROFILE=x aws
s3 ls`, a setter behind reserved words, redirections, payload quotes and empty quoted strings) and the widened
Tier B (any name, after heredoc bodies are removed and quoted strings rewritten); the allow arms pin every read,
search, scoped-temp prefix and quoted or heredoc-only setter the rule leaves alone. Standard library + pytest
only; Python 3.9 compatible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

import pytest

import gate_no_env_vars
import hooklib

HOOKS_DIR = Path(__file__).resolve().parent.parent
ALLOW = 0
BLOCK = 2
RULE_FILE = "no-environment-vars.md"
#: A name the rule does not forbid outright; Tier B must still catch a setter of it.
CUSTOM = "APP_API_BASE"


def decide(command: str, tmp_path: Path) -> hooklib.Decision:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    ctx = hooklib.Context(
        hooklib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=Path(HOOKS_DIR), cwd=Path(tmp_path)
    )
    return gate_no_env_vars.run(ctx)


def assert_blocked(command: str, tmp_path: Path) -> hooklib.Decision:
    decision = decide(command, tmp_path)
    assert decision.exit_code == BLOCK, f"not blocked: {command!r}"
    assert "no-env-vars" in decision.stderr
    return decision


def assert_allowed(command: str, tmp_path: Path) -> None:
    decision = decide(command, tmp_path)
    assert decision.exit_code == ALLOW, f"wrongly refused: {command!r}\n{decision.stderr}"


# ---------------------------------------------------------------------------------------------------------
# the BLOCK direction, part 1: the two measured bypasses, alone and at every command position Bash defines
# ---------------------------------------------------------------------------------------------------------

PREFIX_BYPASS = "AWS_PROFILE=x aws s3 ls"
EXPORT_BYPASS = f"export {CUSTOM}=https://example.invalid"
MEASURED_BYPASSES = (("prefix", PREFIX_BYPASS), ("export", EXPORT_BYPASS))

#: Compound commands holding the bypass `{c}`; a doubled brace is a literal brace.
COMPOUND_TEMPLATES = (
    ("in-for-do-done", "for e in dev; do {c}; done"),
    ("in-if-then-fi", "if true; then {c}; fi"),
    ("in-brace-group", "{{ {c}; }}"),
    ("in-function-parens-body", "f() {{ {c}; }}"),
    ("in-function-keyword-body", "function f {{ {c}; }}"),
    ("in-case-arm", "case a in a) {c};; esac"),
    ("in-named-coproc-group", "coproc c {{ {c}; }}"),
)
#: Words and redirections before the bypass `{c}`.
LEADING_TEMPLATES = (
    ("after-coproc", "coproc {c}"),
    ("after-time-p", "time -p {c}"),
    ("after-time-p-dashdash", "time -p -- {c}"),
    ("after-2-to-1", "2>&1 {c}"),
    ("after-stdin-from-dev-null", "</dev/null {c}"),
    ("after-2-append-log", "2>> log {c}"),
    ("after-fd-10-to-dev-null", "10>/dev/null {c}"),
    ("after-named-fd-to-dev-null", "{{fd}}>/dev/null {c}"),
    ("after-tmpdir-word-and-redirect", "TMPDIR=t 2>/dev/null {c}"),
    ("after-newline", "cd x\n{c}"),
    ("after-backtick", "echo `{c}`"),
)
#: Each redirection operator the gate's docstring lists.
REDIRECTION_OPERATORS = ("<", ">", ">|", ">>", "&>", "&>>", ">&", "<&", "<<", "<<-", "<<<", "<>")
#: `}`, `]]`, `fi`, `done` and `esac`, each directly followed by `then` or `do`, before the bypass `{c}`.
CLOSER_TEMPLATES = (
    ("brace-close-then", "if {{ true; }} then {c}; fi"),
    ("brace-close-do", "while {{ false; }} do {c}; done"),
    ("double-bracket-close-then", "if [[ -n a ]] then {c}; fi"),
    ("double-bracket-close-do", "while [[ -n a ]] do {c}; done"),
    ("fi-then", "if if true; then true; fi then {c}; fi"),
    ("fi-do", "while if true; then true; fi do {c}; done"),
    ("done-then", "if for x in a; do true; done then {c}; fi"),
    ("done-do", "while for x in a; do true; done do {c}; done"),
    ("esac-then", "if case a in a) true;; esac then {c}; fi"),
    ("esac-do", "while case a in a) true;; esac do {c}; done"),
)


def _measured_bypass_cases() -> List[Tuple[str, str]]:
    """Every (id, command): each bypass alone, then at each command position the docstring names."""
    cases: List[Tuple[str, str]] = []
    for bypass_id, bypass in MEASURED_BYPASSES:
        cases.append((bypass_id, bypass))
        for template_id, template in COMPOUND_TEMPLATES + LEADING_TEMPLATES + CLOSER_TEMPLATES:
            cases.append((f"{bypass_id}-{template_id}", template.format(c=bypass)))
        for operator in REDIRECTION_OPERATORS:
            cases.append((f"{bypass_id}-after-{operator}-redirect", f"{operator} w {bypass}"))
    return cases


MEASURED_BYPASS_CASES = _measured_bypass_cases()


@pytest.mark.parametrize(
    "command", [c for _, c in MEASURED_BYPASS_CASES], ids=[case_id for case_id, _ in MEASURED_BYPASS_CASES]
)
def test_the_measured_bypasses_are_blocked_at_every_command_position(command: str, tmp_path: Path) -> None:
    assert_blocked(command, tmp_path)


# ---------------------------------------------------------------------------------------------------------
# the BLOCK direction, part 2: payload quotes, empty quoted strings, wrappers, Tier B's other setters, case
# ---------------------------------------------------------------------------------------------------------

STANDALONE_BLOCKED = (
    ("bash-lc-single-quoted-prefix", "bash -lc 'AWS_PROFILE=x aws s3 ls'"),
    ("bash-c-double-quoted-export", 'bash -c "export AWS_PROFILE=x"'),
    ("bash-lc-ansi-c-quoted-prefix", "bash -lc $'AWS_PROFILE=x aws s3 ls'"),
    ("bash-c-ansi-c-quoted-export", "bash -c $'export AWS_PROFILE=x'"),
    ("bash-c-chained-export", 'bash -c "cd x; export AWS_PROFILE=y"'),
    ("pwsh-command-env-assign", "pwsh -Command '$env:AWS_PROFILE = \"x\"'"),
    ("quoted-redirect-target-then-export", f'>"log" export {CUSTOM}=x'),
    ("empty-double-quotes-before-export", f'""export {CUSTOM}=x'),
    ("empty-double-quotes-inside-export", f'ex""port {CUSTOM}=x'),
    ("empty-double-quotes-after-export", f'export"" {CUSTOM}=x'),
    ("empty-double-then-single-quotes-before-export", f"\"\"''export {CUSTOM}=x"),
    ("empty-ansi-c-quotes-before-export", f"$''export {CUSTOM}=x"),
    ("empty-locale-quotes-before-export", f'$""export {CUSTOM}=x'),
    ("double-quote-inside-single-quotes-then-export", f'echo \'it"s\' ; export {CUSTOM}=x ; echo "q"'),
    ("env-unset-option-then-prefix", "env -u N AWS_PROFILE=x aws s3 ls"),
    ("eval-then-prefix", "eval AWS_PROFILE=x aws s3 ls"),
    ("eval-single-quoted-prefix", "eval 'AWS_PROFILE=x aws s3 ls'"),
    ("short-option-ending-in-c-quoted-prefix", "grep -c 'AWS_PROFILE='"),
    ("prefix-word-after-sudo-wrapped-command", "sudo echo AWS_PROFILE=$AWS_PROFILE"),
    ("prefix-after-env-word-inside-quoted-string", 'git commit -m "use env AWS_PROFILE=x"'),
    ("prefix-after-substitution-inside-quoted-string", 'echo "$(date) AWS_PROFILE=$AWS_PROFILE"'),
    ("quoted-semicolon-export-forbidden", 'echo "; export AWS_PROFILE=x"'),
    ("declare-then-prefix", "declare -r AWS_REGION=eu-central-1 aws s3 ls"),
    ("typeset-then-prefix", "typeset AWS_REGION=eu-central-1"),
    ("prefix-after-another-assignment-word", "TMPDIR=t AWS_PROFILE=x aws s3 ls"),
    ("prefix-after-two-assignment-words", "A=1 B=2 AWS_PROFILE=x aws s3 ls"),
    ("secret-key-prefix", "AWS_SECRET_ACCESS_KEY=abc AWS_ACCESS_KEY_ID=def aws sts get-caller-identity"),
    ("gh-token-prefix", "GH_TOKEN=ghp_x gh issue list"),
    ("github-token-prefix-after-pipe", "cat x | GITHUB_TOKEN=x gh api user"),
    ("gitlab-token-prefix-after-semicolon", "cd repo; GITLAB_TOKEN=x glab issue list"),
    ("export-forbidden-name-without-value", "export AWS_PROFILE"),
    ("export-gh-token-without-value", "AWS_PROFILE=x; export GH_TOKEN"),
    ("export-dashdash-forbidden-name", "export -- AWS_PROFILE=x"),
    ("export-dashdash-custom-name", f"export -- {CUSTOM}=x"),
    ("export-gh-token", "export GH_TOKEN=ghp_x"),
    ("setx-gh-token", "setx GH_TOKEN ghp_x"),
    ("powershell-env-gh-token", "$env:GH_TOKEN = 'ghp_x'"),
    ("cmd-set-gh-token", "set GH_TOKEN=ghp_x"),
    ("setx-custom-name", f"setx {CUSTOM} x"),
    ("powershell-env-assign-custom-name", f"$env:{CUSTOM} = 'x'"),
    ("powershell-env-append-custom-name", f"$env:{CUSTOM} += 'x'"),
    ("powershell-env-append-path", "$env:PATH += ';C:\\tools'"),
    ("cmd-set-custom-name", f"set {CUSTOM}=x"),
    ("export-path", 'export PATH="$PATH:/opt/bin"'),
    ("export-custom-after-and", f"cd x && export {CUSTOM}=x"),
    ("export-custom-after-pipe", f"true | export {CUSTOM}=x"),
    ("export-custom-on-second-line", f"cd x\nexport {CUSTOM}=x"),
    ("export-custom-in-for-body", f"for e in a b; do export {CUSTOM}=$e; done"),
    ("export-custom-after-redirect", f"2>/dev/null export {CUSTOM}=x"),
    ("export-custom-after-unquoted-heredoc", f"cat <<EOF\nbody\nEOF\nexport {CUSTOM}=x"),
    ("dotnet-set-environment-variable", f"[Environment]::SetEnvironmentVariable('{CUSTOM}', 'x')"),
    (
        "dotnet-system-set-environment-variable",
        f"[System.Environment]::SetEnvironmentVariable('{CUSTOM}', 'x', 'User')",
    ),
    ("lower-case-forbidden-prefix", "aws_profile=x aws s3 ls"),
    ("lower-case-export-forbidden", "export aws_profile=x"),
    ("lower-case-gh-token-prefix", "gh_token=x gh pr list"),
    ("mixed-case-powershell-env-forbidden", "$Env:AWS_PROFILE = 'x'"),
    ("mixed-case-setx-forbidden", "SetX Aws_Profile x"),
    ("upper-case-powershell-env-custom-name", f"$ENV:{CUSTOM} = 'x'"),
)


@pytest.mark.parametrize("command", [c for _, c in STANDALONE_BLOCKED], ids=[i for i, _ in STANDALONE_BLOCKED])
def test_payload_quotes_wrappers_empty_quotes_and_tier_b_setters_are_blocked(command: str, tmp_path: Path) -> None:
    assert_blocked(command, tmp_path)


FORBIDDEN_NAMES = ("AWS_PROFILE", "AWS_SECRET_ACCESS_KEY", "aws_region", "GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN")
ORIGINAL_SETTER_TEMPLATES = ("export {name}=x", "setx {name} x", "$env:{name} = 'x'", "set {name}=x")
ORIGINAL_SETTER_BOUNDARIES = ("", "true; ", "true && ", "true || ", "true | ", "true & ", "true\n", "\t")


@pytest.mark.parametrize("boundary", ORIGINAL_SETTER_BOUNDARIES, ids=repr)
@pytest.mark.parametrize("template", ORIGINAL_SETTER_TEMPLATES)
@pytest.mark.parametrize("name", FORBIDDEN_NAMES)
def test_the_original_setters_stay_blocked_for_every_forbidden_name(
    name: str, template: str, boundary: str, tmp_path: Path
) -> None:
    """the original gate's four setters after each of its boundaries: the widening must not lose any of them"""
    assert_blocked(boundary + template.format(name=name), tmp_path)


@pytest.mark.parametrize(
    "command, fragments",
    [
        (PREFIX_BYPASS, ("per-command prefix", "AWS_PROFILE", RULE_FILE)),
        (EXPORT_BYPASS, ("export", CUSTOM, RULE_FILE)),
        (f"setx {CUSTOM} x", ("setx", CUSTOM, RULE_FILE)),
        ("export AWS_PROFILE", ("export NAME", "AWS_PROFILE", RULE_FILE)),
        ("GH_TOKEN=x gh auth status", ("per-command prefix", "GH_TOKEN", RULE_FILE)),
        (f"[Environment]::SetEnvironmentVariable('{CUSTOM}', 'x')", ("SetEnvironmentVariable(", CUSTOM, RULE_FILE)),
    ],
    ids=["prefix", "export-custom", "setx-custom", "export-without-value", "gh-token-prefix", "dotnet"],
)
def test_the_refusal_names_the_form_the_variable_and_the_rule(
    command: str, fragments: Tuple[str, ...], tmp_path: Path
) -> None:
    decision = assert_blocked(command, tmp_path)
    missing = [fragment for fragment in fragments if fragment not in decision.stderr]
    assert missing == [], decision.stderr
    assert "TMPDIR/TEMP/TMP prefix stays allowed" in decision.stderr, "the refusal names the scoped-temp escape"


# ---------------------------------------------------------------------------------------------------------
# the ALLOW direction: reads, searches, scoped-temp prefixes, `export -p`, quoted and heredoc-only setters
# ---------------------------------------------------------------------------------------------------------

ALLOWED_CASES = (
    ("grep-for-export-word", "grep -rn export src/"),
    ("git-grep-for-setx-word", "git grep -n setx -- .claude/hooks"),
    ("grep-for-set-word", "grep -n 'set -e' scripts/*.sh"),
    ("read-dollar-name", "echo $AWS_PROFILE"),
    ("read-braced-name", "echo ${AWS_PROFILE}"),
    ("read-quoted-name-equals-value", 'echo "AWS_PROFILE=$AWS_PROFILE"'),
    ("read-gh-token", "echo ${GH_TOKEN:+set}"),
    ("printenv-all", "printenv"),
    ("printenv-forbidden-name", "printenv AWS_PROFILE"),
    ("env-all", "env"),
    ("env-piped-to-grep", "env | grep AWS_"),
    ("env-running-a-command", "env python -V"),
    ("sudo-quoted-read", 'sudo echo "AWS_PROFILE=$AWS_PROFILE"'),
    ("env-quoted-read", 'env echo "GH_TOKEN=$GH_TOKEN"'),
    ("powershell-env-read", "$env:AWS_PROFILE"),
    ("powershell-env-read-custom-name", f"Write-Output $env:{CUSTOM}"),
    ("powershell-env-read-in-comparison", "if ($env:AWS_PROFILE -eq 'x') { Write-Output yes }"),
    ("aws-cli-explicit-profile", "aws s3 ls --profile dev --region eu-central-1"),
    ("tmpdir-prefix", "TMPDIR=tmp/os-temp python -m pytest test/ci"),
    ("temp-and-tmp-prefixes", "TEMP=tmp/os-temp TMP=tmp/os-temp npm test"),
    ("tmpdir-prefix-before-git", "TMPDIR=/d/tree/tmp/os-temp git status"),
    ("tmpdir-prefix-before-quoted-read", 'TMPDIR=tmp/os-temp echo "$TMPDIR"'),
    ("tmpdir-prefix-before-printenv-forbidden", "TMPDIR=tmp/os-temp printenv AWS_PROFILE"),
    ("custom-name-prefix", f"{CUSTOM}=https://example.invalid npm run dev"),
    ("pythonpath-prefix", "PYTHONPATH=src python -m pytest"),
    ("export-p", "export -p"),
    ("empty-ansi-c-quotes-before-export-p", "$''export -p"),
    ("set-options-only", "set -euo pipefail; python x.py"),
    ("git-config-set-is-no-command-position", "git config set user.name=x"),
    ("custom-setter-in-double-quoted-message", f'git commit -m "export {CUSTOM}=x"'),
    ("custom-setters-after-semicolons-in-single-quotes", f"echo 'x; export {CUSTOM}=x; setx {CUSTOM} x'"),
    ("custom-setter-in-quoted-heredoc-body", f"cat > notes.md <<'EOF'\nexport {CUSTOM}=x\nEOF"),
    (
        "custom-setters-in-unquoted-heredoc-body",
        f"cat <<EOF > f.sh\nexport {CUSTOM}=x\nsetx {CUSTOM} x\nset {CUSTOM}=x\nEOF\necho done",
    ),
    ("custom-setter-in-dash-heredoc-body", f'cat <<-"EOF"\nexport {CUSTOM}=x\nEOF'),
    ("custom-setter-in-spaced-quoted-heredoc-body", f"cat << 'EOF' > notes.md\nexport {CUSTOM}=x\nEOF"),
    (
        "custom-setter-in-spaced-dash-heredoc-body-tab-closed",
        f"cat <<- EOF > f.sh\n\texport {CUSTOM}=x\n\tsetx {CUSTOM} x\n\tEOF\necho done",
    ),
    ("mcp-json-env-block-write", "python -c \"import json; print(json.dumps({'env': {'AWS_PROFILE': 'x'}}))\""),
    ("ordinary-command", "python scripts/run_checks.py"),
)


@pytest.mark.parametrize("command", [c for _, c in ALLOWED_CASES], ids=[i for i, _ in ALLOWED_CASES])
def test_reads_searches_scoped_temp_prefixes_and_quoted_setters_pass(command: str, tmp_path: Path) -> None:
    assert_allowed(command, tmp_path)


READ_TEMPLATES = ("echo ${name}", "echo ${{{name}}}", 'echo "{name}=${name}"', "printenv {name}")


@pytest.mark.parametrize("template", READ_TEMPLATES)
@pytest.mark.parametrize("name", FORBIDDEN_NAMES + (CUSTOM, "PATH", "_x1"))
def test_every_read_of_every_name_is_allowed(name: str, template: str, tmp_path: Path) -> None:
    assert_allowed(template.format(name=name), tmp_path)


def test_an_empty_command_is_allowed(tmp_path: Path) -> None:
    assert_allowed("", tmp_path)


def test_a_non_string_command_reads_as_empty_and_is_allowed(tmp_path: Path) -> None:
    payload = {"tool_name": "Bash", "tool_input": {"command": ["export", "AWS_PROFILE=x"]}}
    ctx = hooklib.Context(hooklib.Payload.parse(json.dumps(payload)), environ={}, hooks_dir=HOOKS_DIR, cwd=tmp_path)
    assert gate_no_env_vars.run(ctx).exit_code == ALLOW


def test_a_crlf_payload_is_read_like_an_lf_one(tmp_path: Path) -> None:
    assert_blocked("cd x\r\nexport AWS_PROFILE=x\r\n", tmp_path)
    assert_allowed(f"cat <<'EOF'\r\nexport {CUSTOM}=x\r\nEOF\r\n", tmp_path)


# ---------------------------------------------------------------------------------------------------------
# the module-local quote rewriter and the heredoc remover, on their own
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command, expected",
    [
        ('ex""port x', "export x"),
        ("$''export -p", "export -p"),
        ('>"log" export X=1', ">%QUOTED% export X=1"),
        ("echo 'it\"s' ; export X=1", "echo %QUOTED% ; export X=1"),
        ("a \"b\" 'c' d", "a %QUOTED% %QUOTED% d"),
        ("a \"b\"'c' d", "a %QUOTED%%QUOTED% d"),
        ("plain words", "plain words"),
    ],
    ids=["touching-run-removed", "ansi-c-run-removed", "target-kept", "leftmost-first", "two", "run", "none"],
)
def test_strip_quoted_rewrites_quoted_strings_as_bash_reads_them(command: str, expected: str) -> None:
    assert gate_no_env_vars._strip_quoted(command, "%QUOTED%") == expected


def test_remove_heredoc_bodies_drops_each_body_and_keeps_the_rest() -> None:
    command = "cat <<EOF > f\nexport X=1\nEOF\necho done\ncat <<-'T'\n\texport Y=1\n\tT\nexport Z=1"
    assert gate_no_env_vars.remove_heredoc_bodies(command=command) == "cat <<EOF > f\necho done\ncat <<-'T'\nexport Z=1"
    assert gate_no_env_vars.remove_heredoc_bodies(command="cat <<<word export X=1") == "cat <<<word export X=1"


# ---------------------------------------------------------------------------------------------------------
# the docstring is the gate's contract: it must keep naming the blocked, allowed and unmatched forms
# ---------------------------------------------------------------------------------------------------------

DOC_BLOCKED_FORMS = (
    "AWS_",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "export NAME",
    "export -- NAME",
    "setx NAME",
    "$env:NAME =",
    "+=",
    "set NAME=",
    "[Environment]::SetEnvironmentVariable(",
    "System.",
    "AWS_PROFILE=x aws s3 ls",
    "export AWS_PROFILE",
    "sudo",
    "eval",
    "declare",
    "typeset",
    "-lc",
    "-Command",
    'bash -c "export AWS_PROFILE=x"',
    "grep -c 'AWS_PROFILE='",
    "heredoc",
)
DOC_ALLOWED_FORMS = ("$NAME", "${NAME}", 'echo "NAME=$NAME"', "printenv", "$env:NAME", "TMPDIR", "export -p")
DOC_UNMATCHED_FORMS = (
    "declare -x",
    "typeset -x",
    "local -x",
    'TMPDIR="a b" AWS_PROFILE=x aws s3 ls',
    "builtin",
    "env -u NAME",
    'env "AWS_PROFILE=x" aws s3 ls',
    'export "AWS_PROFILE=x"',
    "/usr/bin/env AWS_PROFILE=x aws s3 ls",
    "unset",
    "source",
    '"export" AWS_PROFILE=x',
    "\\export AWS_PROFILE=x",
    "New-Item",
    "Set-Item",
    "Copy-Item",
)


@pytest.mark.parametrize(
    "forms", [DOC_BLOCKED_FORMS, DOC_ALLOWED_FORMS, DOC_UNMATCHED_FORMS], ids=["blocked", "allowed", "unmatched"]
)
def test_the_docstring_names_each_form(forms: Tuple[str, ...]) -> None:
    docstring = " ".join((gate_no_env_vars.__doc__ or "").split())
    missing = [form for form in forms if " ".join(form.split()) not in docstring]
    assert missing == [], f"the gate's docstring no longer names: {missing}"
    assert "Not matched" in docstring, "the known-limits list must stay"


def test_the_docstring_carries_no_project_specific_wording() -> None:
    docstring = gate_no_env_vars.__doc__ or ""
    assert "CHESS" not in docstring and "SSM" not in docstring
