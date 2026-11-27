"""Synthetic integration tests for approved functional-unit Git isolation."""

from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

import pytest

from test_proposal_paths import write_proposal


REPO = Path(__file__).parents[1]
HARNESS = REPO / "skills/subagent-driven-development/scripts/sdd-harness.py"


def git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=SDD Test", "-c",
         "user.email=sdd@example.invalid", "-c", "commit.gpgsign=false", *args],
        check=check, capture_output=True, encoding="utf-8",
    )


def cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(HARNESS), *map(str, args)],
        capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8",
             "GIT_AUTHOR_NAME": "SDD Test", "GIT_AUTHOR_EMAIL": "sdd@example.invalid",
             "GIT_COMMITTER_NAME": "SDD Test", "GIT_COMMITTER_EMAIL": "sdd@example.invalid", **(env or {})},
    )


def file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symlink(path, target):
    try:
        path.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        if os.name == "nt" and target.is_dir():
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
                                    capture_output=True)
            if result.returncode == 0:
                return
        pytest.skip(f"cannot create symbolic links: {error}")


def plan_and_approval(unit, *, status="approved", worktree=None):
    plan, task = write_proposal(unit)
    file(plan, plan.read_text(encoding="utf-8").replace("decision: pending", f"decision: {status}"))
    file(task, task.read_text(encoding="utf-8").replace("approval_status: pending", "approval_status: approved"))
    receipt = file(unit / ".tmp/sdd/spec-approval.json", json.dumps({
        "build_plan_sha256": hash_file(plan), "task_specs": {"T01": hash_file(task)},
        "approved_at": datetime.now(timezone.utc).isoformat(), "user_message_ref": "fixture-user-approval",
        **({"worktree_path": str(worktree)} if worktree else {}),
    }))
    return plan, task, receipt


def state_path(unit):
    return unit / ".tmp/sdd/build_plan/state.json"


def build(unit, plan, receipt, *args, **kwargs):
    return cli("init", state_path(unit), "--build-plan", plan, "--evidence", receipt, *args, **kwargs)


@pytest.fixture
def parent(tmp_path):
    parent = tmp_path / "项目 root"
    parent.mkdir()
    git(parent, "init", "--quiet")
    file(parent / "parent.txt", "parent baseline")
    git(parent, "add", "parent.txt")
    git(parent, "commit", "--quiet", "-m", "parent baseline")
    return parent


def test_proposal_reports_root_without_writing_state_or_git(parent):
    unit = parent / "功能单元"
    plan, _, receipt = plan_and_approval(unit, status="pending")
    state = state_path(unit)
    verify = cli("verify-build-plan", state, "--artifact", plan)
    assert verify.returncode == 0, verify.stderr
    assert Path(json.loads(verify.stdout)["unit_git_root"]) == unit.resolve()
    denied = build(unit, plan, receipt)
    assert denied.returncode != 0 and "decision" in denied.stderr
    assert not (unit / ".git").exists()
    assert not state.parent.exists()


def test_approved_siblings_have_independent_head_state_and_evidence(parent):
    left, right = parent / "单元 A", parent / "单元 B"
    parent_head = git(parent, "rev-parse", "HEAD").stdout
    parent_index = (parent / ".git/index").read_bytes()
    for unit in (left, right):
        plan, task, receipt = plan_and_approval(unit)
        file(unit / "private.raw", "synthetic data")
        initialized = build(unit, plan, receipt, env={"GIT_DIR": str(parent / ".git")})
        assert initialized.returncode == 0, initialized.stderr
        assert Path(git(unit, "rev-parse", "--show-toplevel").stdout.strip()) == unit.resolve()
        assert not git(unit, "ls-tree", "-r", "HEAD").stdout
        assert not git(unit, "ls-files").stdout
        git(unit, "add", "specs/build_plan.md")
        git(unit, "commit", "--quiet", "-m", unit.name)
        registration = cli("register-task", state_path(unit), "T01", "--action",
                           "resume_or_redispatch_implementer", "--evidence", task)
        assert registration.returncode == 0, registration.stderr
        report = file(state_path(unit).parent / "task-T01.md",
                      "Status: DONE\nCommit: fixture\nTDD Evidence\n")
        started = cli("transition", state_path(unit), "--to", "task_review_pending",
                      "--evidence", report)
        assert started.returncode == 0, started.stderr
        state = json.loads(state_path(unit).read_text(encoding="utf-8"))
        assert Path(state["refs"]["build_plan"]["path"]) == plan.resolve()
        assert state["evidence"]["task_review_pending"][0]["path"] == str(report.resolve())
    assert git(left, "rev-parse", "HEAD").stdout != git(right, "rev-parse", "HEAD").stdout
    assert git(parent, "rev-parse", "HEAD").stdout == parent_head
    assert (parent / ".git/index").read_bytes() == parent_index
    assert not (parent / ".tmp").exists()
    foreign = state_path(right).parent / "foreign-pass.md"
    file(foreign, "Verdict: PASS")
    denied = cli("transition", state_path(left), "--to", "task_complete", "--evidence", foreign)
    assert denied.returncode != 0 and "outside" in denied.stderr


def test_two_proposals_in_one_unit_use_separate_workspaces(parent):
    unit = parent / "single-unit"
    first_plan, first_task = write_proposal(
        unit, proposal_dir="specs/proposal-01-baseline", plan_name="build_plan_p01.md", batched=True,
    )
    second_plan, second_task = write_proposal(
        unit, proposal_dir="specs/proposal-02-follow-up", plan_name="build_plan_p02.md", task_id="T02", batched=True,
    )
    upstream = Path(os.path.relpath(first_task, second_task.parent)).as_posix()
    file(second_task, second_task.read_text(encoding="utf-8").replace(
        "## 上下游影响\n", f"## 上下游影响\n- 承接的 Proposal／Task：[P01 / T01]({upstream})\n",
    ))

    workspaces = []
    original_evidence = {}
    for plan, task, task_id in ((first_plan, first_task, "T01"), (second_plan, second_task, "T02")):
        state = unit / ".tmp/sdd" / plan.stem / "state.json"
        for result in (cli("verify-build-plan", state, "--artifact", plan),
                       cli("verify-task-spec", state, "--artifact", task, "--build-plan", plan)):
            assert result.returncode == 0, result.stderr

        file(plan, plan.read_text(encoding="utf-8").replace("decision: pending", "decision: approved"))
        file(task, task.read_text(encoding="utf-8").replace("approval_status: pending", "approval_status: approved"))
        receipt = file(state.parent / "spec-approval.json", json.dumps({
            "build_plan_sha256": hash_file(plan), "task_specs": {task_id: hash_file(task)},
            "batch_id": "B01", "approved_at": datetime.now(timezone.utc).isoformat(),
            "user_message_ref": f"approval-{task_id}",
        }))
        initialized = cli("init", state, "--build-plan", plan, "--evidence", receipt)
        assert initialized.returncode == 0, initialized.stderr
        bound_state = json.loads(state.read_text(encoding="utf-8"))
        assert Path(bound_state["refs"]["build_plan"]["path"]) == plan.resolve()
        assert bound_state["spec_approval"]["task_specs"] == {task_id: hash_file(task)}
        resolved = cli("resolve-workspace", plan, task_id, "--evidence", task, "--worktree", unit)
        assert resolved.returncode == 0, resolved.stderr
        assert Path(resolved.stdout.strip()) == state.parent.resolve()
        workspaces.append(resolved.stdout.strip())
        if plan == first_plan:
            original_evidence = {record: record.read_bytes() for record in (state, receipt)}

    assert len(set(workspaces)) == 2
    assert all(record.read_bytes() == content for record, content in original_evidence.items())
    resumed = cli("resolve-workspace", first_plan, "T01", "--evidence", first_task, "--worktree", unit)
    assert resumed.returncode == 0, resumed.stderr
    assert resumed.stdout.strip() == workspaces[0]
    wrong_task = cli("resolve-workspace", second_plan, "T02", "--evidence", first_task, "--worktree", unit)
    assert wrong_task.returncode != 0 and "approved Task MD bytes" in wrong_task.stderr


@pytest.mark.parametrize("nested_exists", [False, True])
@pytest.mark.parametrize("staged_deletion", [False, True])
def test_parent_tracking_blocks_and_reports_files(parent, nested_exists, staged_deletion):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    tracked = file(unit / "parent-owned.txt", "parent's data")
    git(parent, "add", str(tracked))
    git(parent, "commit", "--quiet", "-m", "already tracking file")
    if staged_deletion:
        git(parent, "rm", "--cached", "--", str(tracked))
    if nested_exists:
        git(unit, "init", "--quiet")
    parent_head = git(parent, "rev-parse", "HEAD").stdout
    parent_index = (parent / ".git/index").read_bytes()
    denied = build(unit, plan, receipt)
    assert denied.returncode != 0
    assert "parent-owned.txt" in denied.stderr and "manually" in denied.stderr
    assert (unit / ".git").exists() == nested_exists
    assert not state_path(unit).exists()
    assert git(parent, "rev-parse", "HEAD").stdout == parent_head
    assert (parent / ".git/index").read_bytes() == parent_index


@pytest.mark.parametrize("track_linked_worktree", [False, True])
def test_later_parent_gitlink_blocks_registered_worktree(parent, track_linked_worktree):
    unit = parent / "unit"
    worktree = parent / "linked" if track_linked_worktree else unit
    plan, task, receipt = plan_and_approval(unit, worktree=worktree)
    if track_linked_worktree:
        prepared = cli("prepare-git", plan, "--evidence", receipt)
        assert prepared.returncode == 0, prepared.stderr
        git(unit, "worktree", "add", "--quiet", "--detach", str(worktree))
    initialized = build(worktree, plan, receipt, "--worktree", worktree)
    assert initialized.returncode == 0, initialized.stderr
    state = state_path(worktree)
    assert cli("status", state).returncode == 0

    git(parent, "add", "--", worktree.name)
    assert git(parent, "ls-files", "--stage", "--", worktree.name).stdout.startswith("160000 ")
    parent_index = (parent / ".git/index").read_bytes()
    parent_head = git(parent, "rev-parse", "HEAD").stdout
    workspace = {p: p.read_bytes() for p in state.parent.rglob("*") if p.is_file()}

    denied = cli("register-task", state, "T01", "--action", "resume_or_redispatch_implementer", "--evidence", task)
    assert denied.returncode != 0 and "Parent Git tracks" in denied.stderr
    helper = cli("resolve-workspace", plan, "--worktree", worktree)
    assert helper.returncode != 0 and "Parent Git tracks" in helper.stderr
    assert {p: p.read_bytes() for p in state.parent.rglob("*") if p.is_file()} == workspace
    assert git(parent, "rev-parse", "HEAD").stdout == parent_head
    assert (parent / ".git/index").read_bytes() == parent_index


def test_wrong_state_path_missing_receipt_and_stale_hash_never_init(parent):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    missing = cli("init", state_path(unit), "--build-plan", plan)
    assert missing.returncode != 0
    wrong_root = build(parent, plan, receipt)
    assert wrong_root.returncode != 0
    assert not state_path(parent).parent.exists()
    plan.write_text(plan.read_text(encoding="utf-8") + "\nEdited after approval\n", encoding="utf-8")
    stale = build(unit, plan, receipt)
    assert stale.returncode != 0 and "fingerprint" in stale.stderr
    assert not (unit / ".git").exists()
    assert not state_path(unit).parent.exists()


def test_prepare_then_init_in_same_logical_worktree(parent):
    unit, linked = parent / "unit", parent / "linked checkout"
    plan, _, receipt = plan_and_approval(unit)
    prepared = cli("prepare-git", plan, "--evidence", receipt)
    assert prepared.returncode == 0, prepared.stderr
    assert not state_path(unit).parent.exists()
    git(unit, "worktree", "add", "--detach", str(linked))
    unapproved = build(linked, plan, receipt, "--worktree", linked)
    assert unapproved.returncode != 0 and "approved worktree_path" in unapproved.stderr
    assert not state_path(linked).parent.exists()

    approval = json.loads(receipt.read_text(encoding="utf-8"))
    linked_receipt = file(receipt.with_name("linked-approval.json"),
                          json.dumps({**approval, "worktree_path": str(linked)}))
    foreign = parent / "other repository"
    foreign.mkdir()
    git(foreign, "init", "--quiet")
    wrong = build(foreign, plan, linked_receipt, "--worktree", foreign)
    assert wrong.returncode != 0 and "worktree" in wrong.stderr
    assert not state_path(foreign).parent.exists()
    valid = build(linked, plan, linked_receipt, "--worktree", linked)
    assert valid.returncode == 0, valid.stderr
    state = json.loads(state_path(linked).read_text(encoding="utf-8"))
    assert Path(state["git"]["unit_root"]) == unit.resolve()
    assert Path(state["git"]["worktree"]) == linked.resolve()
    assert not state_path(unit).parent.exists()
    duplicate = build(unit, plan, receipt)
    assert duplicate.returncode != 0 and "already has an SDD state" in duplicate.stderr
    assert not state_path(unit).parent.exists()
    assert state_path(linked).is_file()
    assert cli("status", state_path(linked)).returncode == 0



def test_unborn_unit_keeps_sensitive_files_already_staged_out_of_baseline(parent):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    git(unit, "init", "--quiet")
    file(unit / "staged.raw", "staged synthetic private data")
    git(unit, "add", "staged.raw")
    staged = git(unit, "ls-files", "--stage").stdout
    index_bytes = (unit / ".git/index").read_bytes()
    result = build(unit, plan, receipt)
    assert result.returncode == 0, result.stderr
    assert not git(unit, "ls-tree", "-r", "HEAD").stdout
    assert git(unit, "ls-files", "--stage").stdout == staged
    assert (unit / ".git/index").read_bytes() == index_bytes


def test_gitdir_alias_cannot_bind_parent_metadata(parent):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    file(unit / ".git", f"gitdir: {(parent / '.git').as_posix()}\n")
    old_head = git(parent, "rev-parse", "HEAD").stdout
    denied = build(unit, plan, receipt)
    assert denied.returncode != 0 and "local .git" in denied.stderr
    assert not state_path(unit).exists()
    assert git(parent, "rev-parse", "HEAD").stdout == old_head


@pytest.fixture
def native_shell():
    if os.name == "nt":
        git_bash = Path(shutil.which("git")).parents[1] / "bin/bash.exe"
    else:
        git_bash = shutil.which("bash")
    if not git_bash or not Path(git_bash).is_file():
        pytest.skip("Git Bash or Bash is unavailable")

    def shell(name, *args, directory):
        return subprocess.run(
            [str(git_bash), str(HARNESS.parent / name), "-C", str(directory), *map(str, args)],
            capture_output=True, encoding="utf-8", env={**os.environ, "SDD_PYTHON": sys.executable},
        )

    return shell


def test_native_shell_helpers_cannot_write_evidence_for_another_unit(parent, native_shell):
    unit = parent / "unit"

    def shell(name, *args, directory=unit):
        return native_shell(name, *args, directory=directory)

    plan, task, receipt = plan_and_approval(unit)
    initialized = build(unit, plan, receipt)
    assert initialized.returncode == 0, initialized.stderr
    baseline = git(unit, "rev-parse", "HEAD").stdout.strip()
    brief = shell("task-brief", plan, "T01", directory=plan.parent)
    assert brief.returncode == 0, brief.stderr
    workspace = state_path(unit).parent
    assert (workspace / "task-T01-brief.md").read_text(encoding="utf-8") == task.read_text(encoding="utf-8")
    other_path = parent / "brief.md"
    output_attempt = shell("task-brief", plan, "T01", other_path)
    assert output_attempt.returncode != 0 and "outside" in output_attempt.stderr
    wrong_repository = shell("task-brief", plan, "T01", directory=parent)
    assert wrong_repository.returncode != 0 and "worktree" in wrong_repository.stderr
    assert not other_path.exists()
    assert not (parent / ".tmp").exists()

    git(unit, "add", "specs")
    git(unit, "commit", "--quiet", "-m", "fixture specs")
    head = git(unit, "rev-parse", "HEAD").stdout.strip()
    package = shell("review-package", plan, baseline, head, directory=plan.parent)
    assert package.returncode == 0, package.stderr
    assert len(list(workspace.glob("review-*.diff"))) == 1
    wrong_output = shell("review-package", plan, baseline, head, parent / "wrong.diff")
    assert wrong_output.returncode != 0 and "outside" in wrong_output.stderr
    assert not (parent / "wrong.diff").exists()

    foreign_directory = parent / "foreign"
    foreign_directory.mkdir()
    defaults = [
        ("task-brief", (plan, "T01"), workspace / "task-T01-brief.md"),
        ("review-package", (plan, baseline, head), next(workspace.glob("review-*.diff"))),
    ]
    for command, args, default in defaults:
        default.unlink()
        symlink(default, foreign_directory)
        denied = shell(command, *args)
        assert denied.returncode != 0 and "outside" in denied.stderr
    assert not list(foreign_directory.iterdir())


def hardlink(path, target):
    try:
        os.link(target, path)
    except OSError as error:
        pytest.skip(f"cannot create hard links: {error}")


@pytest.mark.parametrize("command", ["task-brief", "review-package"])
def test_native_shell_helpers_reject_hardlinked_output(parent, native_shell, command):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    initialized = build(unit, plan, receipt)
    assert initialized.returncode == 0, initialized.stderr
    baseline = git(unit, "rev-parse", "HEAD").stdout.strip()
    output = state_path(unit).parent / "output.md"
    external = file(parent / "other-output.md", "external content")
    hardlink(output, external)

    args = (plan, "T01")
    if command == "review-package":
        git(unit, "add", "specs")
        git(unit, "commit", "--quiet", "-m", "fixture specs")
        head = git(unit, "rev-parse", "HEAD").stdout.strip()
        args = (plan, baseline, head)
    denied = native_shell(command, *args, output, directory=unit)
    assert external.read_text(encoding="utf-8") == "external content"
    assert denied.returncode != 0 and "hard link" in denied.stderr


@pytest.mark.parametrize("name", ["events.jsonl", ".harness.lock"])
def test_harness_rejects_hardlinked_sidecar_before_init(parent, name):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    workspace = state_path(unit).parent
    workspace.mkdir()
    external = file(parent / "other-sidecar", "external content")
    hardlink(workspace / name, external)

    denied = build(unit, plan, receipt)
    assert external.read_text(encoding="utf-8") == "external content"
    assert denied.returncode != 0 and "hard link" in denied.stderr
    assert not state_path(unit).exists()
    assert not (unit / ".git").exists()


def test_structured_legacy_plan_resolves_only_its_recorded_workspace(parent):
    unit = parent / "legacy unit"
    plan, task, receipt = plan_and_approval(unit)
    file(plan, "<!-- Historical Build Plan -->\n" + "\n".join(line for line in plan.read_text(encoding="utf-8").splitlines()
                         if not line.startswith(("- 功能单元 Git 根目录", "- path_schema:"))))
    state = state_path(unit)
    args = ("resolve-workspace", plan, "T01", "--evidence", task, "--worktree", parent)
    assert cli(*args).returncode == 1
    assert not state.exists()
    file(task, "\n".join(line for line in task.read_text(encoding="utf-8").splitlines()
                         if not line.startswith("- 主入口路径：")))
    plan_ref = {"path": str(plan.resolve()), "sha256": hash_file(plan)}
    task_identity = {"task_spec_path": str(task.resolve()), "task_spec_sha256": hash_file(task)}
    file(state, json.dumps({"refs": {"build_plan": plan_ref}, "phase": "building",
                            "status": "building_incomplete", "tasks": {"T01": task_identity},
                            "evidence": {}, "fix_round": 0}))
    assert cli("verify-build-plan", state, "--artifact", plan).returncode == 1
    for name in ("analysis-state.json", "building/manifest.json", "runtime/manifest.json"):
        file(state.parent / name, json.dumps({"build_plan": plan_ref}))
    file(state.parent / "events.jsonl", json.dumps({
        "action": "init", "timestamp": datetime.now(timezone.utc).isoformat(),
    }) + "\n")
    assert cli("verify-build-plan", state, "--artifact", plan).returncode == 0
    assert cli("verify-task-spec", state, "--artifact", task, "--build-plan", plan).returncode == 0
    result = cli(*args)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == state.parent.resolve()
    assert build(unit, plan, receipt).returncode == 1
    file(plan, plan.read_text(encoding="utf-8") + "\nChanged plan")
    assert cli(*args).returncode == 1
    assert cli("prepare-git", plan, "--evidence", receipt).returncode == 1
    assert not (unit / ".git").exists()


def test_worktree_plan_directory_alias_is_rejected_before_workspace_mutation(parent):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    alias = unit / "specs alias"
    symlink(alias, plan.parent)
    denied = build(unit, alias / plan.name, receipt)
    assert denied.returncode != 0 and "without an alias" in denied.stderr
    assert not (unit / ".git").exists()
    assert not state_path(unit).exists()

    initialized = build(unit, plan, receipt)
    assert initialized.returncode == 0, initialized.stderr
    foreign = parent / "state alias"
    symlink(foreign, state_path(unit).parent)
    wrong_state = cli("status", foreign / "state.json")
    assert wrong_state.returncode != 0 and "functional-unit workspace" in wrong_state.stderr


def test_build_plan_alias_is_rejected_before_workspace_mutation(parent):
    unit = parent / "unit"
    plan, _, receipt = plan_and_approval(unit)
    alias = unit / "specs/other-name.md"
    symlink(alias, plan)
    wrong_state = unit / ".tmp/sdd/other-name/state.json"
    denied = cli("init", wrong_state, "--build-plan", alias, "--evidence", receipt)
    assert denied.returncode != 0
    assert not (unit / ".git").exists()
    assert not wrong_state.exists()
    assert build(unit, alias, receipt).returncode != 0
    assert not (unit / ".git").exists()
    valid = build(unit, plan, receipt)
    assert valid.returncode == 0, valid.stderr
    assert cli("status", state_path(unit)).returncode == 0
    result = cli("resolve-workspace", alias, "--worktree", unit)
    assert result.returncode != 0 and "without an alias" in result.stderr
