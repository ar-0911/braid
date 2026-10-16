"""Generated files: lockfiles, snapshots, compiled assets. Merging them as text gives nonsense.

`braid settings regen "package-lock.json=npm install --package-lock-only; poetry.lock=poetry lock --no-update"`
maps file patterns to the command that rebuilds them. When landing touches such a file on both sides (or
it conflicts), braid takes the base branch's copy, merges everything else, then runs the command in the
merged tree so the file is rebuilt from the merged sources. The predictor doesn't report these files as
conflicts, since they will be regenerated.

A rule's command can also be `ours` (keep the base branch's copy) or `theirs` (keep the incoming copy),
for generated files that are rebuilt later anyway.
"""
import fnmatch
import subprocess

from . import gitutil


def rules(store):
    """[(pattern, command)] from the regen setting."""
    out = []
    for part in (store.cfg("regen") or "").split(";"):
        if "=" in part:
            pat, cmd = part.split("=", 1)
            if pat.strip() and cmd.strip():
                out.append((pat.strip(), cmd.strip()))
    return out


def rule_for(path, rule_list):
    name = path.rsplit("/", 1)[-1]
    for pat, cmd in rule_list:
        if fnmatch.fnmatch(path, pat) or ("/" not in pat and fnmatch.fnmatch(name, pat)):
            return cmd
    return None


def generated(paths, rule_list):
    return {p for p in paths if rule_for(p, rule_list)}


def regenerate(store, cwd, targets, conflicted, rule_list):
    """Rebuild targets in the merge in progress (or just made) at cwd. Returns (ok, detail)."""
    commands = []
    for f in sorted(targets):
        cmd = rule_for(f, rule_list)
        if cmd in ("ours", "theirs"):
            if f in conflicted:
                gitutil.git("checkout", f"--{cmd}", "--", f, cwd=cwd, check=False)
        else:
            if f in conflicted:
                gitutil.git("checkout", "--ours", "--", f, cwd=cwd, check=False)
            if cmd not in commands:
                commands.append(cmd)
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=1800,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, f"regenerating with `{cmd}` timed out"
        if proc.returncode != 0:
            return False, f"`{cmd}` failed: {(proc.stderr or proc.stdout).strip()[-500:]}"
    existing = [f for f in sorted(targets) if (gitutil.Path(cwd) / f).exists()]
    if existing:
        gitutil.git("add", "--", *existing, cwd=cwd)
    gone = [f for f in sorted(targets) if f not in existing]
    if gone:
        gitutil.git("rm", "-q", "--cached", "--ignore-unmatch", "--", *gone, cwd=cwd, check=False)
    return True, "regenerated " + ", ".join(sorted(targets)) + (f" with {'; '.join(commands)}" if commands else "")
