r"""no-env-vars — PreToolUse(Bash) gate enforcing the no-environment-vars rule.

Blocks (exit 2) when the command SETS a shell environment variable, judged in two tiers; either tier blocks, and
both ignore letter case, because Windows treats variable names case-insensitively (16 of 117 rows in a measured
command corpus spelled the name lower- or mixed-case). Reading a variable is not blocked. Profiles and regions are
resolved through the project's aws_config at session creation, and git-host tokens are read from project-local
credential files by the wrapper. The `env` blocks in .mcp.json and settings files are scoped subprocess
configuration, not shell variables, and are unaffected.

Tier A, the forbidden names (`AWS_*`, `GH_TOKEN`, `GITHUB_TOKEN`, `GITLAB_TOKEN`; GH_TOKEN is the gh CLI's own name
for the GitHub token), matches the raw command:
  - the original four setters, `export NAME=`, `setx NAME`, PowerShell `$env:NAME =` and `set NAME=`, at the
    original boundaries (the start, `;`, `&`, `|` or whitespace) and directly after the payload quote named below,
    so `bash -c "export AWS_PROFILE=x"` is blocked, and `export -- NAME=`, such as `export -- AWS_PROFILE=x`, too;
  - the per-command prefix `NAME=`, such as `AWS_PROFILE=x aws s3 ls` (measured as a bypass of a setter-only gate),
    at a command position: the start, or after `;`, `&`, `|`, `(`, `)`, `]]`, a newline or a backtick, past any run
    of the reserved words `!`, `{`, `}`, `do`, `done`, `then`, `else`, `elif`, `fi`, `if`, `while`, `until`,
    `esac`, `coproc` and `time` (with or without `-p`, with or without `--`), of `function NAME` and
    `coproc NAME`, of redirections (an optional digit or `{NAME}` descriptor, one of `<`, `>`, `>|`, `>>`, `&>`,
    `&>>`, `>&`, `<&`, `<<`, `<<-`, `<<<` and `<>`, then the target, such as `2>&1`, `2>/dev/null`,
    `10>/dev/null`, `{fd}>/dev/null`, `2>> log` or `< in`) and of `NAME=value` words;
  - that prefix directly after another `NAME=value` word; at the start of any later whitespace-delimited word,
    before the next `;`, `&`, `|` or newline, after an `env`, `sudo`, `eval`, `declare` or `typeset` word, so
    `sudo echo AWS_PROFILE=$AWS_PROFILE`, `env -u N AWS_PROFILE=x aws s3 ls` and `eval AWS_PROFILE=x aws s3 ls`
    are blocked; and after the quote, with or without a leading `$`, that opens the payload of `-c`, of a
    short-option word ending in `c` such as `-lc`, of `-Command` or of `eval`, so `bash -lc 'AWS_PROFILE=x aws s3
    ls'`, `bash -c $'export AWS_PROFILE=x'`, `eval 'AWS_PROFILE=x aws s3 ls'` and `grep -c 'AWS_PROFILE='` are
    blocked;
  - those positions inside a quoted string too, so `git commit -m "use env AWS_PROFILE=x"` and
    `echo "$(date) AWS_PROFILE=$AWS_PROFILE"` are blocked, and a quoted `; export AWS_PROFILE=x` stays blocked.

Tier B, any name, matches the command after each heredoc body is removed (the lines between a `<<[-]['"]WORD['"]`
that is not part of `<<<`, with or without blanks before `WORD` as in `cat << 'EOF'`, and the line `WORD`, which
after `<<-` may start with tabs) and its quoted strings are rewritten by this module's `_strip_quoted`: in one
left-to-right scan that reads `'…'`, `"…"`, `$'…'` and `$"…"`, a run of adjacent quoted strings that a letter,
digit or `_` touches is removed and every other quoted string becomes one placeholder word, so `ex""port`,
`""''export`, `$''export`, `echo 'it"s' ; export APP_API_BASE=x` and `>"log" export APP_API_BASE=x` are read as
Bash reads them:
  - `export NAME` or `export -- NAME`, with or without `=value`, such as `export APP_API_BASE=…`,
    `export -- APP_API_BASE=x` or a bare `export AWS_PROFILE` (which exports a variable assigned earlier), `setx
    NAME` and `set NAME=`, at a command position as Tier A defines it, reserved words included;
  - `$env:NAME =` or `+=`;
  - `[Environment]::SetEnvironmentVariable(`, with an optional `System.` before `Environment`.

The block message names the matched form, the variable and no-environment-vars.md.

Allowed: every read Tier A does not state as blocked, such as `$NAME`, `${NAME}`, `echo "NAME=$NAME"`, `printenv`,
`env` without an assignment and `$env:NAME` without `=`; a search for a setter's word, such as
`grep -rn export src/`; a per-command prefix of any name that is not forbidden, `TMPDIR`, `TEMP` and `TMP`
included (no-environment-vars.md's second clarification, the scoped temp directory); `export -p`, `$''export -p`
included; and a custom-name setter that appears only inside a quoted string or a heredoc body.

Not matched (a known limit of the gate, never a permission): `declare -x` and `typeset -x` of a name that is not
forbidden; `local -x` of any name; a prefix after a quoted value or target that holds whitespace, such as
`TMPDIR="a b" AWS_PROFILE=x aws s3 ls`; an `export` of a name that is not forbidden after an `eval`, `command` or
`builtin` word, such as `eval export APP_API_BASE=x`; a `setx` of such a name after an `env`, `eval` or `command`
word; `env -u NAME` that is followed by no unquoted forbidden `NAME=` word; an assignment word quoted after `env`,
`sudo`, `declare`, `typeset` or `export`, such as `env "AWS_PROFILE=x" aws s3 ls`, `export "AWS_PROFILE=x"` or
`env -S '…'`; an `env` named by a path or as `env.exe`, such as `/usr/bin/env AWS_PROFILE=x aws s3 ls`; `unset`; a
file run by `source`; a setter word spelled with a quoted string that holds characters, a backslash escape or an
expansion, such as `"export" AWS_PROFILE=x`, `e"xport" APP_API_BASE=x`, `\export AWS_PROFILE=x` or
`${X}export APP_API_BASE=x`; a setter of a name that is not forbidden after a word that expands to nothing, such
as `$X export APP_API_BASE=x`, after an unpaired escaped quote, such as
`echo \"; export APP_API_BASE=x; echo \"`, or after a quoted string that holds an escaped quote, such as
`echo $'\'' ; export APP_API_BASE=x ; echo 'z'`; a setter of a name that is not forbidden on a line after a
heredoc opener inside a quoted string, such as `git commit -m "a <<EOF"` followed by `export APP_API_BASE=x` on
the next line; a custom-name setter inside a quoted `bash -c`, `pwsh -Command` or `eval` payload, such as
`eval 'export APP_API_BASE=x'`; and the PowerShell Environment-provider cmdlets `New-Item`, `Set-Item` and
`Copy-Item` on `Env:`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import hooklib as lib

HOOK = "no-env-vars"
EVENT = "pre-tool-use"  # the dispatcher runs this gate on this event
ORDER = 10  # framework gates 10..90; a project gate takes >100 (or <10 to run first)
SHELL_TOOLS = {"Bash", "shell", "execute_bash", "execute_cmd", "executeBash"}
TOOLS = SHELL_TOOLS  # PreToolUse only: the tool names this gate judges
RULE_FILE = "no-environment-vars.md"
#: Both tiers ignore letter case: Windows treats variable names case-insensitively.
FLAGS = re.IGNORECASE
GROUP_NAME = "name"
GROUP_DASH = "dash"
GROUP_WORD = "word"

#: The names the rule forbids outright; Tier A matches only these. The NAME is matched case-insensitively on
#: its own too, so a pattern compiled without FLAGS still reads `export aws_profile=x` as setting the variable.
FORBIDDEN = r"(?i:(AWS_[A-Z0-9_]+|GH_TOKEN|GITHUB_TOKEN|GITLAB_TOKEN))"
#: A shell name; Tier B matches any.
NAME = r"[A-Za-z_][A-Za-z0-9_]*"
#: The word Tier B puts in place of a quoted string: no shell name, reserved word or redirection.
PLACEHOLDER = "%QUOTED%"

_FORBIDDEN_NAME = r"(?P<name>" + FORBIDDEN + r")"
_ANY_NAME = r"(?P<name>" + NAME + r")"
#: The start, or a `;`, `&`, `|`, `(`, `)`, newline, backtick or `]]`.
_SEPARATOR = r"(?:^|[;&|()\n`]|\]\])"
#: The start of a whitespace-delimited word: the start of the command, or after whitespace or a separator.
_WORD_START = r"(?:^|(?<=[\s;&|()`])|(?<=\]\]))"
#: One character of an unquoted word.
_WORD_CHARACTER = r"[^\s;&|()<>`]"
_RESERVED_WORD = (
    r"(?:!|\{|\}|do|done|then|else|elif|fi|if|while|until|esac|time(?:[ \t]+-p)?(?:[ \t]+--)?"
    r"|function[ \t]+" + NAME + r"|coproc(?:[ \t]+" + NAME + r")?)"
)
#: A redirection (Bash manual, Redirections): an optional descriptor, the operator, then the target word.
_REDIRECTION = r"(?:\d+|\{" + NAME + r"\})?(?:&>>|&>|<<<|<<-|<<|<>|<&|<|>>|>\||>&|>)[ \t]*" + _WORD_CHARACTER + r"+"
_ASSIGNMENT_WORD = NAME + r"=" + _WORD_CHARACTER + r"*"
#: Any run of reserved words, redirections and `NAME=value` words, each followed by blanks. A run never crosses a
#: newline: the newline is a separator, so the line after it is judged from its own start (and the search stays
#: linear on a long multi-line command).
_RUN = r"(?:(?:" + _RESERVED_WORD + r"|" + _REDIRECTION + r"|" + _ASSIGNMENT_WORD + r")[ \t]+)*"
#: Where a command word stands: a separator, then the run.
COMMAND_POSITION = _SEPARATOR + r"[ \t]*" + _RUN
#: The quote, with or without a leading `$`, that opens the payload of `-c`, of `-…c`, of `-Command` or of `eval`.
_PAYLOAD_QUOTE = _WORD_START + r"(?:-[a-z]*c|-command|eval)\s+\$?['\"]"
#: The original boundaries before a setter, and the payload quote.
_SETTER_BOUNDARY = r"(?:^|[;&|\s]|" + _PAYLOAD_QUOTE + r")"
#: The words after which any later word of the same simple command may be a prefix.
_WRAPPER_WORD = r"(?:env|sudo|eval|declare|typeset)"
#: One simple command for the wrapper scan: blanks and unquoted-word characters, up to `;`, `&`, `|` or a newline.
SIMPLE_COMMAND = re.compile(r"(?:[ \t]|[^\s;&|])+")
#: An `env`, `sudo`, `eval`, `declare` or `typeset` word, and the blanks after it.
WRAPPER = re.compile(_WORD_START + _WRAPPER_WORD + r"[ \t]+", FLAGS)

#: One quoted string as Bash reads it: `"…"`, `'…'`, and their `$"…"` (locale) and `$'…'` (ANSI-C) spellings.
QUOTED_STRING_RE = re.compile(r"""\$?"[^"]*"|\$?'[^']*'""")
WORD_CHARACTER_RE = re.compile(r"\w")


@dataclass(frozen=True)
class Form:
    """One blocked form: the label the block message names, and its compiled pattern."""

    label: str
    pattern: re.Pattern[str]

    def search(self, *, text: str) -> Optional[re.Match[str]]:
        return self.pattern.search(text)


class WrapperPrefixForm(Form):
    """A prefix at the start of any later word of a simple command that holds an `env`, `sudo`, `eval`, `declare`
    or `typeset` word. Each simple command is scanned once, from its first such word: a prefix after a later one
    is after the first one too, and rescanning from every such word would make a long command quadratic.
    """

    def search(self, *, text: str) -> Optional[re.Match[str]]:
        for simple_command in SIMPLE_COMMAND.finditer(text):
            wrapper = WRAPPER.search(text, simple_command.start(), simple_command.end())
            if wrapper:
                found = self.pattern.search(text, wrapper.end(), simple_command.end())
                if found:
                    return found
        return None


def _form(*, label: str, pattern: str) -> Form:
    return Form(label=label, pattern=re.compile(pattern, FLAGS))


#: Tier A: the original four setters of a forbidden name, at the original boundaries and after a payload quote.
SETTERS = [
    _form(label="export NAME=", pattern=_SETTER_BOUNDARY + r"export\s+(?:--\s+)?" + _FORBIDDEN_NAME + r"\s*="),
    _form(label="setx NAME", pattern=_SETTER_BOUNDARY + r"setx\s+" + _FORBIDDEN_NAME + r"(\s|=)"),
    _form(label="$env:NAME =", pattern=r"\$env:" + _FORBIDDEN_NAME + r"\s*="),
    _form(label="set NAME=", pattern=_SETTER_BOUNDARY + r"set\s+" + _FORBIDDEN_NAME + r"\s*="),
]
PREFIX_LABEL = "per-command prefix NAME="
#: Tier A: the per-command prefix of a forbidden name.
PREFIXES = [
    _form(
        label=PREFIX_LABEL,
        pattern=r"(?:" + _SEPARATOR + r"|" + _PAYLOAD_QUOTE + r")[ \t]*" + _RUN + _FORBIDDEN_NAME + r"=",
    ),
    _form(label=PREFIX_LABEL, pattern=_WORD_START + _ASSIGNMENT_WORD + r"[ \t]+" + _FORBIDDEN_NAME + r"="),
    WrapperPrefixForm(label=PREFIX_LABEL, pattern=re.compile(r"(?<=[ \t])" + _FORBIDDEN_NAME + r"=", FLAGS)),
]
TIER_A = SETTERS + PREFIXES
#: Tier B: a setter of any name, on the command with heredoc bodies removed and quoted strings rewritten.
TIER_B = [
    _form(label="export NAME", pattern=COMMAND_POSITION + r"export\s+(?:--\s+)?" + _ANY_NAME),
    _form(label="setx NAME", pattern=COMMAND_POSITION + r"setx\s+" + _ANY_NAME),
    _form(label="$env:NAME = or +=", pattern=r"\$env:" + _ANY_NAME + r"\s*\+?="),
    _form(label="set NAME=", pattern=COMMAND_POSITION + r"set\s+" + _ANY_NAME + r"\s*="),
    _form(
        label="[Environment]::SetEnvironmentVariable(",
        pattern=r"\[(?:System\.)?Environment\]::SetEnvironmentVariable\(",
    ),
]
#: The variable a `SetEnvironmentVariable(` call names, read from the raw command for the block message.
DOTNET_VARIABLE = re.compile(r"SetEnvironmentVariable\(\s*\$?['\"]?" + _ANY_NAME, FLAGS)
#: A heredoc opener `<<[-]['"]WORD['"]` that is not part of `<<<`; Bash also accepts blanks before `WORD`.
HEREDOC_OPENER = re.compile(r"(?<!<)<<(?!<)(?P<dash>-?)[ \t]*['\"]?(?P<word>\w+)['\"]?")


def _quoted_runs(command: str) -> List[Tuple[int, int, int]]:
    """(start, end, number of strings) of each run of adjacent quoted strings, in one left-to-right scan."""
    runs: List[Tuple[int, int, int]] = []
    for match in QUOTED_STRING_RE.finditer(command):
        if runs and runs[-1][1] == match.start():
            run_start, _, count = runs[-1]
            runs[-1] = (run_start, match.end(), count + 1)
        else:
            runs.append((match.start(), match.end(), 1))
    return runs


def _is_word_character(text: str) -> bool:
    """True when `text` is one letter, digit or `_`; the empty text beyond either end of a command is not."""
    return bool(WORD_CHARACTER_RE.fullmatch(text))


def _strip_quoted(command: str, placeholder: str) -> str:
    """The command with its quoted strings rewritten as Bash reads them, for Tier B.

    Unlike `hooklib.strip_quoted`, which removes double-quoted strings and then single-quoted ones, this finds
    `'…'`, `"…"`, `$'…'` and `$"…"` in ONE left-to-right scan that takes the leftmost string first, so the `"` in
    `'it"s'` opens none. Quoted strings with nothing between them form one run. A run that a letter, digit or `_`
    directly precedes or follows is removed, so `ex""port` and `$''export` read as `export`; each string of any
    other run is replaced in place by `placeholder`, so a quoted redirection target stays that redirection's
    target and never looks like a command word.
    """
    pieces: List[str] = []
    cursor = 0
    for start, end, count in _quoted_runs(command):
        pieces.append(command[cursor:start])
        touches_word = _is_word_character(command[start - 1 : start]) or _is_word_character(command[end : end + 1])
        if not touches_word:
            pieces.append(placeholder * count)
        cursor = end
    pieces.append(command[cursor:])
    return "".join(pieces)


def remove_heredoc_bodies(*, command: str) -> str:
    """The command without the lines between each heredoc opener and the line `WORD` that ends its body.

    The openers are found on the raw text, so one inside a quoted string opens a body too; a body whose `WORD`
    line never comes runs to the end of the command. `<<-` also ends its body on `WORD` after leading tabs.
    """
    kept: List[str] = []
    pending: List[Tuple[str, bool]] = []
    for line in command.split("\n"):
        if pending:
            word, strips_tabs = pending[0]
            if (line.lstrip("\t") if strips_tabs else line) == word:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend(
            (opener.group(GROUP_WORD), bool(opener.group(GROUP_DASH))) for opener in HEREDOC_OPENER.finditer(line)
        )
    return "\n".join(kept)


def _first_match(*, forms: List[Form], text: str) -> Optional[Tuple[Form, re.Match[str]]]:
    for form in forms:
        match = form.search(text=text)
        if match:
            return form, match
    return None


def _variable(*, match: re.Match[str], command: str) -> str:
    """The variable the matched form sets; a `SetEnvironmentVariable(` call names it in its first argument."""
    if GROUP_NAME in match.re.groupindex:
        return match.group(GROUP_NAME)
    named = DOTNET_VARIABLE.search(command)
    return named.group(GROUP_NAME) if named else "named by its first argument"


def _message(*, ctx: lib.Context, form: Form, variable: str) -> str:
    return (
        f"{HOOK}: this command sets the environment variable {variable} through the form `{form.label}`, which "
        f"{ctx.host.rules_dir}/{RULE_FILE} forbids. This system hosts multiple projects and shell env vars leak "
        "across them. Pass profile/region explicitly (boto3.Session(profile_name=..., region_name=...), the AWS "
        "CLI's --profile/--region), read other configuration from the project's config files, and let the "
        "project's git wrapper read its token from its credentials file. A per-command TMPDIR/TEMP/TMP prefix "
        "stays allowed."
    )


def run(ctx: lib.Context) -> lib.Decision:
    command = ctx.payload.command
    if not command:
        return lib.allow()
    found = _first_match(forms=TIER_A, text=command)
    if found is None:
        cleaned = _strip_quoted(remove_heredoc_bodies(command=command), PLACEHOLDER)
        found = _first_match(forms=TIER_B, text=cleaned)
    if found is None:
        return lib.allow()
    form, match = found
    return lib.block(_message(ctx=ctx, form=form, variable=_variable(match=match, command=command)))
