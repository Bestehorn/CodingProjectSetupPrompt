"""scoped-temp-init — SessionStart. Guarantees this tree's scoped temp directory exists AND that the local
settings file points TMPDIR/TEMP/TMP at it, writing the env block itself when it is missing.

Agent tooling leaks unbounded scratch into the SHARED OS temp directory (jsii-kernel-*, cdk.out<hash>,
bundling-temp-*). A per-tree temp directory makes that residue attributable and its cleanup safe while sibling
sessions run. The env values are static and per tree, so they were a manual step that was skipped in practice;
this hook closes the loop. Decisions: an already-configured TMPDIR/TEMP/TMP is never fought; a settings file
that is not a JSON object is never touched; the write is atomic; the exit is always 0; silent when everything
is already right.
"""

from __future__ import annotations

import json
import os
import tempfile

import hooklib as lib

HOOK = "scoped-temp-init"
EVENT = "session-start"  # the dispatcher runs this gate on this event
ORDER = 20  # framework gates 10..90; a project gate takes >100 (or <10 to run first)


def run(ctx: lib.Context) -> lib.Decision:
    project = ctx.project_dir
    scoped = project / "tmp" / "os-temp"
    try:
        scoped.mkdir(parents=True, exist_ok=True)
    except OSError:
        return lib.allow(
            stderr=(
                f"{HOOK}: could not create {scoped} — TMPDIR/TEMP/TMP may point at a missing directory, so tooling\n"
                "will fall back to the shared OS temp dir and its residue will not be attributable to this tree.\n"
            )
        )

    settings = project / ctx.host.config_dir / "settings.local.json"
    try:
        data: object = {}
        if settings.is_file():
            data = json.loads(lib.read_text(settings) or "{}")
            if not isinstance(data, dict):
                return lib.allow(stdout=_invalid(scoped, ctx))
        assert isinstance(data, dict)
        env = data.get("env")
        if not isinstance(env, dict):
            env = {}
        if env.get("TMPDIR") or env.get("TEMP") or env.get("TMP"):
            return lib.allow()  # already right — say nothing
        target = str(scoped.resolve())
        for name in ("TMPDIR", "TEMP", "TMP"):
            env[name] = target
        data["env"] = env
        settings.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(settings.parent),
            prefix=".settings.local.",
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(data, handle, indent=2)
            handle.write("\n")
        finally:
            handle.close()
        os.replace(handle.name, str(settings))
    except json.JSONDecodeError:
        return lib.allow(stdout=_invalid(scoped, ctx))
    except Exception as exc:  # noqa: BLE001 — never wedge a session over a temp dir
        return lib.allow(
            stdout=(
                f"Scoped temp NOT configured and the env block could not be written ({exc}). Tooling will write\n"
                "into the shared OS temp directory, where jsii-kernel-* and cdk.out<hash> residue accumulates\n"
                f"unattributably. Point TMPDIR/TEMP/TMP in {ctx.host.config_dir}/settings.local.json at {scoped} "
                "(ABSOLUTE path).\n"
            )
        )
    return lib.allow(
        stdout=(
            f"Scoped temp CONFIGURED: wrote the TMPDIR/TEMP/TMP env block into "
            f"{ctx.host.config_dir}/settings.local.json\n"
            f"pointing at {target} — it takes effect from the NEXT session; this session still uses the previous\n"
            "temp settings.\n"
        )
    )


def _invalid(scoped, ctx: lib.Context) -> str:
    return (
        f"Scoped temp NOT configured, and {ctx.host.config_dir}/settings.local.json is not a valid JSON object —\n"
        f"NOT touching it. Repair the file, or add the env block yourself: TMPDIR/TEMP/TMP -> {scoped} "
        "(ABSOLUTE path).\n"
    )
