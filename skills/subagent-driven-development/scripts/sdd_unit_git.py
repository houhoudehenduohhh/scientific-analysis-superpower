"""Bind SDD execution to the Git root declared in an approved Build Plan."""

import os
from pathlib import Path
import re
import stat
import subprocess


ROOT_LABEL = "功能单元 Git 根目录"
GIT_LOCAL_ENV = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_DIR", "GIT_GRAFT_FILE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_INTERNAL_SUPER_PREFIX",
    "GIT_NO_REPLACE_OBJECTS", "GIT_OBJECT_DIRECTORY", "GIT_PREFIX",
    "GIT_QUARANTINE_PATH", "GIT_REPLACE_REF_BASE", "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
}


def plan_root(plan_path, *, required=True):
    plan = Path(plan_path).resolve(strict=True)
    if Path(os.path.abspath(plan_path)) != plan:
        raise ValueError(f"Build Plan path must resolve without an alias: {plan}")
    text = plan.read_text(encoding="utf-8")
    fields = list(re.finditer(r"(?m)^[ \t]*-[ \t]*" + ROOT_LABEL + r"[ \t]*[:：][ \t]*([^\n]*)$", text))
    if not fields and not required:
        return None
    section = re.search(r"(?ms)^##[ \t]+目标与边界[ \t]*\n(.*?)(?=^#{1,2}[ \t]|\Z)", text)
    if len(fields) != 1 or not section or not section.start(1) <= fields[0].start() < section.end(1):
        raise ValueError(f"Build Plan must declare one {ROOT_LABEL} field in 目标与边界")
    value = re.fullmatch(r"`([^`]+)`", fields[0][1].strip())
    if not value:
        raise ValueError(f"{ROOT_LABEL} must be a backtick-delimited resolved absolute directory")
    candidate = Path(value[1])
    if not candidate.is_absolute() or not candidate.is_dir() or candidate != candidate.resolve():
        raise ValueError(f"{ROOT_LABEL} must be an existing resolved absolute directory: {candidate}")
    inside(plan, candidate, "Build Plan", unit_paths=True)
    return candidate.resolve()


def git(root, *args, check=True, input_text=None):
    env = {key: value for key, value in os.environ.items() if key.upper() not in GIT_LOCAL_ENV}
    result = subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True, input=input_text,
                            encoding="utf-8", errors="surrogateescape")
    if check and result.returncode:
        raise ValueError(f"Git failed at {root}: {result.stderr.strip() or ' '.join(args)}")
    return result


def discover_worktree(directory):
    result = git(directory, "rev-parse", "--show-toplevel", check=False)
    if result.returncode:
        raise ValueError(f"cannot discover a Git worktree from {directory}: {result.stderr.strip()}")
    return Path(result.stdout.strip()).resolve()


def root_repo(root):
    if not (root / ".git").exists():
        return False
    discovered = discover_worktree(root)
    if discovered != root:
        raise ValueError(f"expected exact Git worktree root {root}; Git resolved {discovered}")
    return True


def common_dir(root):
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()).resolve()


def standalone_repo(unit):
    if not root_repo(unit):
        return False
    metadata = unit / ".git"
    if not metadata.is_dir() or metadata.resolve() != metadata or common_dir(unit) != metadata:
        raise ValueError(f"approved functional-unit Git root must own its local .git directory: {unit}")
    return True


def check_parent_tracking(root):
    conflicts = []
    for parent in root.parents:
        if not root_repo(parent):
            continue
        pathspec = ":(literal)" + root.relative_to(parent).as_posix()
        indexed = git(parent, "ls-files", "--cached", "-z", "--", pathspec).stdout
        committed = ""
        if head(parent):
            committed = git(parent, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", pathspec).stdout
        conflicts.extend(f"{parent}: {path}" for path in sorted(set((indexed + committed).split("\0")) - {""}))
    if conflicts:
        raise ValueError("Parent Git tracks paths inside the functional-unit root. Resolve ownership manually:\n"
                         + "\n".join(conflicts))


def head(root):
    result = git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False)
    if result.returncode not in {0, 1}:
        raise ValueError(f"Unable to read Git HEAD at {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def select_worktree(unit, supplied=None):
    if supplied is None:
        return unit
    worktree = Path(supplied).resolve(strict=True)
    if worktree == unit:
        return unit
    if worktree.is_dir() and standalone_repo(unit) and root_repo(worktree) and common_dir(unit) == common_dir(worktree):
        records = git(unit, "worktree", "list", "--porcelain", "-z").stdout.split("\0")
        if any(entry.startswith("worktree ") and Path(entry[9:]).resolve() == worktree for entry in records):
            return worktree
    raise ValueError(f"worktree does not belong to approved functional-unit Git root {unit}: {worktree}")


def prepare(unit, worktree):
    check_parent_tracking(unit)
    if worktree != unit:
        check_parent_tracking(worktree)
    if not standalone_repo(unit):
        git(unit, "init", "--quiet")
        if not standalone_repo(unit):
            raise ValueError(f"Git init did not create the exact approved repository at {unit}")
    if not head(unit):
        # Write the empty tree directly. The unit index stays untouched even
        # with files already staged, and update-ref accepts only an unborn HEAD.
        tree = git(unit, "mktree", input_text="").stdout.strip()
        baseline = git(unit, "-c", "commit.gpgsign=false", "commit-tree", tree,
                       "-m", "chore: establish SDD baseline").stdout.strip()
        result = git(unit, "update-ref", "HEAD", baseline, "0" * len(baseline), check=False)
        if result.returncode and not head(unit):
            raise ValueError(f"could not write the functional-unit baseline at {unit}: {result.stderr.strip()}")
    commit = head(worktree)
    if not commit:
        raise ValueError(f"functional-unit worktree requires a commit: {worktree}")
    return {"unit_root": str(unit), "worktree": str(worktree), "common_dir": str(common_dir(unit)),
            "baseline_commit": commit}


def workspace(worktree, plan):
    return worktree / ".tmp" / "sdd" / Path(plan).stem


def state_path(worktree, plan):
    return workspace(worktree, plan) / "state.json"


def verify_state_location(path, worktree, plan):
    expected = state_path(worktree, plan)
    inside(expected, worktree, "SDD state", unit_paths=True)
    if Path(os.path.abspath(path)) != expected or expected.resolve() != expected:
        raise ValueError(f"state must be at the functional-unit workspace: {expected}")
    for name in (".harness.lock", "events.jsonl", "analysis-state.json",
                 "building/manifest.json", "runtime/manifest.json"):
        sidecar = expected.parent / name
        if inside(sidecar, worktree, "SDD workspace path", unit_paths=True) != sidecar:
            raise ValueError(f"SDD workspace path resolves outside its declared location: {sidecar}")
    for name in (".harness.lock", "events.jsonl"):
        reject_hardlink(expected.parent / name)
    return expected


def reject_hardlink(path):
    try:
        metadata = Path(path).stat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
        raise ValueError(f"SDD workspace file has multiple hard links: {path}")


def verify_binding(state, path):
    binding = state["git"]
    unit = Path(binding["unit_root"])
    worktree = select_worktree(unit, binding["worktree"])
    if not standalone_repo(unit) or common_dir(worktree) != Path(binding["common_dir"]) or not head(worktree):
        raise ValueError(f"functional-unit Git worktree changed: {worktree}")
    check_parent_tracking(unit)
    if worktree != unit:
        check_parent_tracking(worktree)
    verify_state_location(path, worktree, state["refs"]["build_plan"]["path"])
    return worktree


def inside(path, root, label, *, unit_paths=False):
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"{label} is outside {root}: {candidate}")
    if unit_paths and any((parent / ".git").exists() for parent in candidate.parents
                          if parent != root and parent.is_relative_to(root)):
        raise ValueError(f"{label} crosses a nested Git repository inside {root}: {candidate}")
    return candidate


def initialize_workspace(path):
    ignore = path.parent.parent / ".gitignore"
    if ignore.resolve() != ignore:
        raise ValueError(f"SDD workspace ignore path resolves outside its declared location: {ignore}")
    ignore.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ignore.open("x", encoding="utf-8") as stream:
            stream.write("*\n")
    except FileExistsError:
        pass
