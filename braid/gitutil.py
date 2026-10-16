"""Thin wrappers around the git CLI."""
import os
import subprocess
import tempfile
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(*args, cwd=None, env=None, check=True, input=None):
    """Run git and return (returncode, stdout). Raises GitError if check and rc != 0."""
    full_env = None
    if env:
        full_env = os.environ.copy()
        full_env.update(env)
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=full_env, input=input,
        capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.returncode, proc.stdout


def out(*args, cwd=None, env=None):
    return git(*args, cwd=cwd, env=env)[1].strip()


def toplevel(cwd=None):
    return Path(out("rev-parse", "--show-toplevel", cwd=cwd))


def common_dir(cwd=None):
    """The .git dir shared by all worktrees (absolute)."""
    p = Path(out("rev-parse", "--git-common-dir", cwd=cwd))
    if not p.is_absolute():
        p = (Path(cwd or os.getcwd()) / p).resolve()
    return p


def rev(ref, cwd=None):
    """Commit OID for ref, or "" if it doesn't exist."""
    rc, stdout = git("rev-parse", "--verify", "--quiet", ref + "^{commit}", cwd=cwd, check=False)
    return stdout.strip() if rc == 0 else ""


def snapshot_worktree(worktree):
    """Return a commit OID capturing the worktree's current files, committed or not.

    Uses a throwaway index so the agent's real index and files are untouched.
    Returns HEAD itself when there is nothing uncommitted.
    """
    head = rev("HEAD", cwd=worktree)
    fd, tmp_index = tempfile.mkstemp(prefix="braid-index-")
    os.close(fd)
    os.unlink(tmp_index)  # git wants to create it itself
    env = {"GIT_INDEX_FILE": tmp_index}
    try:
        git("read-tree", "HEAD", cwd=worktree, env=env)
        git("add", "-A", cwd=worktree, env=env)
        tree = out("write-tree", cwd=worktree, env=env)
    finally:
        if os.path.exists(tmp_index):
            os.unlink(tmp_index)
    if tree == out("rev-parse", "HEAD^{tree}", cwd=worktree):
        return head
    return out(
        "commit-tree", tree, "-p", head, "-m", "braid wip snapshot", cwd=worktree,
        env={"GIT_AUTHOR_NAME": "braid", "GIT_AUTHOR_EMAIL": "braid@localhost",
             "GIT_COMMITTER_NAME": "braid", "GIT_COMMITTER_EMAIL": "braid@localhost"},
    )


def changed_paths(base, commit, cwd=None):
    """Paths changed on `commit` since its merge-base with `base`."""
    mb = out("merge-base", base, commit, cwd=cwd)
    if not mb:
        return set()
    names = out("diff", "--name-only", "--no-renames", mb, commit, cwd=cwd)
    return {n for n in names.splitlines() if n}


def merge_preview(a, b, cwd=None):
    """Simulate merging a and b in memory. Returns (clean: bool, conflicted_paths: list, messages: str)."""
    rc, stdout = git("merge-tree", "--write-tree", "--name-only", "--no-messages", a, b,
                     cwd=cwd, check=False)
    if rc not in (0, 1):
        raise GitError(f"merge-tree {a} {b} failed with exit {rc}")
    lines = stdout.splitlines()
    files = [l for l in lines[1:] if l]  # first line is the merged tree OID
    return rc == 0, files


def is_clean(worktree):
    return out("status", "--porcelain", "--untracked-files=normal", cwd=worktree) == ""


def current_branch(worktree):
    rc, stdout = git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=worktree, check=False)
    return stdout.strip() if rc == 0 else None


def worktrees(repo):
    """List of dicts with path, head, branch for every worktree."""
    result, cur = [], {}
    for line in out("worktree", "list", "--porcelain", cwd=repo).splitlines() + [""]:
        if not line:
            if cur:
                result.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
    return result


def conflicted_files(worktree):
    names = out("diff", "--name-only", "--diff-filter=U", cwd=worktree)
    return [n for n in names.splitlines() if n]
