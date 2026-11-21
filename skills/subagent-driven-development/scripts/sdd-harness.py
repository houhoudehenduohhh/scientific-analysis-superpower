#!/usr/bin/env python3
"""Deterministic SDD phase harness with three manifest support."""
import argparse
import glob
import hashlib
import json
import os
import tempfile
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BUILD_PLAN_TITLE = "# Build Plan（构建计划）"

# State transitions and exposed actions are kept in one table.
STATES = {
    "proposal": {"building_incomplete"}, "building_incomplete": {"task_review_pending"},
    "task_review_pending": {"task_complete", "fix_round_pending"},
    "fix_round_pending": {"re_review_pending", "user_decision_pending"},
    "re_review_pending": {"task_complete", "fix_round_pending", "user_decision_pending"},
    "task_complete": {"task_review_pending", "final_review_pending"},
    "final_review_pending": {"building_audit_pending"}, "building_audit_pending": {"building_audit_gate"},
    "building_audit_gate": {"runtime_authorized"}, "user_decision_pending": set(),
    "runtime_authorized": {"runtime_step_pending"}, "runtime_step_pending": {"runtime_step_review_pending"},
    "runtime_step_review_pending": {"runtime_fix_pending", "milestone_audit_pending"},
    "runtime_fix_pending": {"runtime_step_pending", "user_decision_pending", "building_incomplete", "proposal"},
    "milestone_audit_pending": {"milestone_audit_gate"}, "milestone_audit_gate": {"runtime_step_pending", "final_chain_audit_pending"},
    "final_chain_audit_pending": {"runtime_finish_pending"}, "runtime_finish_pending": set(),
}
NEXT = {
 "proposal":["resume_or_redispatch_proposer"], "building_incomplete":["resume_or_redispatch_implementer"],
 "task_review_pending":["dispatch_task_reviewer"], "fix_round_pending":["dispatch_fix_agent"], "re_review_pending":["dispatch_reviewer"],
 "task_complete":["dispatch_next_task","dispatch_final_review"], "final_review_pending":["dispatch_final_review"],
 "building_audit_pending":["create_building_audit"], "building_audit_gate":["wait_for_user_decision"],
 "runtime_authorized":["execute_runtime_step"], "runtime_step_pending":["execute_runtime_step"],
 "runtime_step_review_pending":["dispatch_runtime_step_reviewer"],
 "runtime_fix_pending":["retry_runtime_step","return_building","return_proposal"],
 "milestone_audit_pending":["dispatch_milestone_audit"], "milestone_audit_gate":["wait_for_user_decision"],
 "final_chain_audit_pending":["dispatch_final_chain_audit"], "runtime_finish_pending":["dispatch_runtime_finish"],
 "user_decision_pending":["wait_for_user_decision"],
 "runtime_authorization_pending":["record_runtime_authorization"],
 "final_chain_audit_gate":["wait_for_user_decision"],
 "runtime_finished":[]}
PHASE_STATUSES = {
 "proposal":{"proposal"},
 "building":{"building_incomplete","task_review_pending","fix_round_pending","re_review_pending","task_complete","final_review_pending","user_decision_pending"},
 "building_audit":{"building_audit_pending","building_audit_gate"},
 "runtime":{"runtime_authorization_pending","runtime_authorized","runtime_step_pending","runtime_step_review_pending","runtime_fix_pending"},
 "runtime_audit":{"milestone_audit_pending","milestone_audit_gate","final_chain_audit_pending","final_chain_audit_gate"},
 "runtime_finish":{"runtime_finish_pending","runtime_finished"}}
ACTION_TARGETS = {
 "resume_or_redispatch_proposer":{"building_incomplete"}, "resume_or_redispatch_implementer":{"building_incomplete"},
 "dispatch_task_reviewer":{"task_review_pending"}, "dispatch_fix_agent":{"fix_round_pending"}, "dispatch_reviewer":{"re_review_pending"},
 "dispatch_next_task":{"task_review_pending"}, "dispatch_final_review":{"final_review_pending"}, "create_building_audit":{"building_audit_pending"},
 "wait_for_user_decision":{"building_audit_gate","milestone_audit_gate","final_chain_audit_gate","user_decision_pending"},
 "record_runtime_authorization":{"runtime_authorized"},
 "execute_runtime_step":{"runtime_step_pending"}, "dispatch_runtime_step_reviewer":{"runtime_step_review_pending"},
 "retry_runtime_step":{"runtime_step_pending"}, "return_building":{"building_incomplete"}, "return_proposal":{"proposal"},
 "dispatch_milestone_audit":{"milestone_audit_pending"}, "dispatch_final_chain_audit":{"final_chain_audit_pending"}, "dispatch_runtime_finish":{"runtime_finish_pending"}}

def _phase(status, *, runtime=False):
    if status == "user_decision_pending" and runtime:
        return "runtime"
    for phase, statuses in PHASE_STATUSES.items():
        if status in statuses: return phase
    raise SystemExit("unknown harness status: " + str(status))

for _status, _actions in NEXT.items():
    for _action in _actions:
        if _action not in ACTION_TARGETS: raise RuntimeError("action missing mapping: " + _action)

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def digest(path):
    h=hashlib.sha256();
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

class HarnessLock:
    def __init__(self, root):
        self.path = Path(root) / ".harness.lock"
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise SystemExit("harness locked by another process") from None
        return self

    def release(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None

def lock(root):
    return HarnessLock(root).acquire()

def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=Path(path).name + ".", dir=Path(path).parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def evidence_record(raw):
    p=Path(raw).resolve()
    if not p.is_file(): raise SystemExit("missing evidence: " + str(p))
    return {"path":str(p), "sha256":digest(p)}

def evidence_records(raw):
    return [evidence_record(x) for x in raw.split(",") if x]


def legacy_workspace_base(root, plan_path):
    relative = plan_path.relative_to(root).parts
    unit = plan_path.parents[1] if len(relative) >= 3 and relative[-2:] == ("specs", "build_plan.md") else root
    return unit / ".tmp" / "sdd"


def matching_legacy_state(path, plan, *, root=None):
    import runtime_harness as runtime
    import sdd_unit_git as unit_git

    if path.name != "state.json" or not path.is_file() or path.absolute() != path.resolve():
        return None
    state = read(path)
    if (state.get("refs", {}).get("build_plan") != plan or state.get("status") not in NEXT
            or state.get("phase") != _phase(state["status"], runtime="runtime" in state)
            or not isinstance(state.get("tasks"), dict) or not isinstance(state.get("evidence"), dict)
            or not isinstance(state.get("fix_round"), int)):
        return None
    plan_path = Path(plan["path"])
    if state.get("git"):
        unit = unit_git.plan_root(plan_path)
        worktree = unit_git.verify_binding(state, path)
        if unit != Path(state["git"]["unit_root"]):
            return None
        baseline = state["git"]["baseline_commit"]
        if not re.fullmatch(r"[0-9a-f]{40,64}", baseline):
            return None
        if unit_git.git(worktree, "merge-base", "--is-ancestor", baseline, "HEAD", check=False).returncode:
            return None
        approval_ref = state["refs"].get("spec_approval")
        if not approval_ref:
            return None
        _validate_record(approval_ref, "spec_approval")
        unit_git.inside(approval_ref["path"], unit, "Spec approval receipt", unit_paths=True)
        approval = read(Path(approval_ref["path"]))
        if (approval != state.get("spec_approval") or approval.get("build_plan_sha256") != plan["sha256"]
                or not approval.get("user_message_ref") or not approval.get("task_specs")):
            return None
        runtime.timestamp(approval.get("approved_at"))
        return state
    # A pre-binding workspace still carries the generated manifest set and
    # initialization event, and belongs to the Git tree containing its plan.
    if root is None:
        root = unit_git.discover_worktree(plan_path.parent)
    if not plan_path.is_relative_to(root) or not unit_git.head(root):
        return None
    base = legacy_workspace_base(root, plan_path)
    folder = path.parent
    if (folder.parent != base or
            (folder.name != plan_path.stem and not folder.name.startswith(plan_path.stem + "-"))):
        return None
    for name in ("analysis-state.json", "building/manifest.json", "runtime/manifest.json"):
        manifest = folder / name
        if not manifest.is_file() or manifest.resolve() != manifest or read(manifest).get("build_plan") != plan:
            return None
    events = folder / "events.jsonl"
    if (not events.is_file() or events.resolve() != events
            or not any(json.loads(line).get("action") == "init"
                       for line in events.read_text(encoding="utf-8").splitlines() if line.strip())):
        return None
    return state


def matching_historical_task(path, artifact, expected_plan=None):
    import sdd_layout

    state = read(path) if path.is_file() else {}
    plan = state.get("refs", {}).get("build_plan")
    if not plan or (expected_plan is not None and plan != expected_plan) or evidence_record(plan["path"]) != plan:
        return False
    if sdd_layout.structured_plan(Path(plan["path"]).read_text(encoding="utf-8")):
        return False
    if matching_legacy_state(path, plan) is None:
        return False
    task = evidence_record(artifact)
    approved = state.get("spec_approval", {}).get("task_specs")
    return any(item.get("task_spec_path") == task["path"]
               and item.get("task_spec_sha256") == task["sha256"]
               and (approved is None or approved.get(task_id) == task["sha256"])
               for task_id, item in state["tasks"].items())


def legacy_workspace(worktree, plan):
    import sdd_unit_git as unit_git

    root = unit_git.discover_worktree(worktree)
    path = Path(plan["path"])
    if not path.is_relative_to(root):
        raise ValueError("rootless Build Plan is outside its historical Git worktree")
    base = legacy_workspace_base(root, path)
    candidates = [base / path.stem, *base.glob(glob.escape(path.stem) + "-*")]
    matches = [(folder, state) for folder in candidates
               if (state := matching_legacy_state(folder / "state.json", plan, root=root)) is not None
               and not state.get("git")]
    if len(matches) != 1:
        raise ValueError("rootless Build Plan requires exactly one matching pre-binding SDD workspace")
    return matches[0]


def _validate_record(rec, label):
    if not isinstance(rec, dict) or not rec.get("path") or not re.fullmatch(r"[0-9a-f]{64}", str(rec.get("sha256", ""))):
        raise SystemExit("invalid evidence schema: " + label)
    p=Path(rec["path"])
    if not p.is_file() or digest(p) != rec["sha256"]:
        raise SystemExit("evidence fingerprint changed: " + str(p))

def validate_evidence(state):
    refs = state.get("refs", {})
    for name in ("build_plan",):
        if name not in refs:
            raise SystemExit("required reference missing: " + name)
        _validate_record(refs[name], name)
    for key, ref in refs.items(): _validate_record(ref, key)
    for key, records in state.get("evidence", {}).items():
        if isinstance(records, dict): records=[records]
        for rec in records or []: _validate_record(rec, key)
    for task_id, task in state.get("tasks", {}).items():
        if not task.get("task_spec_path") or not task.get("task_spec_sha256"):
            raise SystemExit("task spec reference missing: " + task_id)
        _validate_record({"path": task["task_spec_path"], "sha256": task["task_spec_sha256"]}, "task:" + task_id)
    status = state.get("status")
    if status in NEXT and state.get("next_allowed_actions") != NEXT[status]:
        raise SystemExit("next_allowed_actions mismatch")
    acceptance = state.get("user_acceptance")
    if acceptance and acceptance.get("accepted"):
        if acceptance.get("accepted_state") != "building_audit_gate":
            raise SystemExit("invalid user acceptance state")
        audit = state.get("evidence", {}).get("building_audit")
        if not audit:
            raise SystemExit("user acceptance missing Building Audit evidence")
        expected = hashlib.sha256(json.dumps(audit, sort_keys=True).encode()).hexdigest()
        if acceptance.get("building_audit_sha256") != expected:
            raise SystemExit("user acceptance fingerprint changed")

def sync_manifests(root, state):
    root=Path(root); refs=state.get("refs", {}); status=state.get("status"); phase=_phase(status, runtime="runtime" in state)
    view={"build_plan":refs.get("build_plan"), "build_plan_sha256":refs.get("build_plan",{}).get("sha256") if refs.get("build_plan") else None}
    if "git" in state:
        view["git"] = state["git"]
    write(root/"analysis-state.json", {"phase":phase,"status":status,**view,"building_manifest":"building/manifest.json","runtime_manifest":"runtime/manifest.json","next_allowed_actions":list(NEXT.get(status, []))})
    bp=read(root/"building/manifest.json") if (root/"building/manifest.json").exists() else {}
    if state.get("building_history") and not state.get("tasks"):
        bp = {"final_review": "pending", "building_audit": "blocked"}
    bp.update({"phase":"building","status":status if phase in {"proposal", "building", "building_audit"} else bp.get("status","building_audit_gate"),**view,"runtime_manifest":"runtime/manifest.json","tasks":state.get("tasks",bp.get("tasks",{})),"evidence":state.get("evidence",bp.get("evidence",{})),"user_acceptance":state.get("user_acceptance",bp.get("user_acceptance"))})
    audit_binding = (state.get("building_gate") or {}).get("audit_binding")
    if audit_binding is None:
        bp.pop("audit_binding", None)
    else:
        bp["audit_binding"] = audit_binding
    write(root/"building/manifest.json",bp)
    rp=read(root/"runtime/manifest.json") if (root/"runtime/manifest.json").exists() else {}
    if state.get("runtime_history") and "runtime" not in state:
        rp = {"authorized_nodes": [], "steps": {}, "milestone_audit": "blocked", "final_chain_audit": "blocked"}
    rp.update({"phase":"runtime","status":status if phase in {"runtime", "runtime_audit", "runtime_finish"} else "blocked",**view,"building_manifest":"building/manifest.json","evidence":state.get("evidence",rp.get("evidence",{})),"user_acceptance":state.get("user_acceptance",rp.get("user_acceptance"))})
    if "runtime" in state:
        rp.update(state["runtime"])
        rp["status"] = status
    write(root/"runtime/manifest.json",rp)
    reconcile_manifests(root)

def reconcile_manifests(root):
    root=Path(root); a=read(root/"analysis-state.json"); b=read(root/"building/manifest.json"); r=read(root/"runtime/manifest.json")
    for key in ("build_plan_sha256", "git"):
        if a.get(key)!=b.get(key) or a.get(key)!=r.get(key): raise SystemExit("manifest reference mismatch: "+key)
    if a.get("building_manifest")!="building/manifest.json" or a.get("runtime_manifest")!="runtime/manifest.json": raise SystemExit("manifest link mismatch")
    if a.get("phase") in {"runtime", "runtime_audit", "runtime_finish"} and r.get("status")!=a.get("status"): raise SystemExit("runtime manifest status mismatch")
    if a.get("phase") in {"proposal", "building", "building_audit"} and b.get("status")!=a.get("status"): raise SystemExit("building manifest status mismatch")
    if b.get("phase") != "building" or r.get("phase") != "runtime": raise SystemExit("manifest phase mismatch")

def main():
    import runtime_harness
    import sdd_layout
    import sdd_unit_git as unit_git

    # Accept the documented command-first form as well as the historical
    # STATE COMMAND form used by existing SDD workspaces.
    commands={"init", "status", "transition", "allowed", "verify", "verify-report", "verify-task-spec", "verify-build-plan", "register-task", "gate", "proposal-rebind",
              "prepare-git", "resolve-workspace"} | runtime_harness.COMMANDS
    if len(sys.argv) > 2 and sys.argv[1] in commands:
        sys.argv[1], sys.argv[2] = sys.argv[2], sys.argv[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("action", choices=sorted(commands))
    ap.add_argument("value", nargs="?")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--artifact", default="")
    ap.add_argument("--report-kind", choices=["building", "runtime"])
    ap.add_argument("--to")
    ap.add_argument("--action", dest="allowed_action")
    ap.add_argument("--user-accepted", action="store_true")
    ap.add_argument("--build-plan", default="")
    ap.add_argument("--worktree")
    ap.add_argument("--affected-task", action="append", default=[])
    ap.add_argument("--reusable-output", action="append", default=[])
    ap.add_argument("--invalidated-output", action="append", default=[])
    ap.add_argument("--inheritance-constraint", action="append", default=[])
    ap.add_argument("--actor")
    args = ap.parse_args()
    path = Path(args.state)
    try:
        if args.action == "verify-build-plan":
            if not args.artifact:
                raise ValueError("verify-build-plan requires --artifact BUILD_PLAN")
            result = verify_build_plan_layout(args.artifact)
            plan_record = evidence_record(args.artifact)
            content = Path(plan_record["path"]).read_text(encoding="utf-8")
            unit = unit_git.plan_root(args.artifact, required=False)
            if sdd_layout.structured_plan(content):
                sdd_layout.proposal_layout(args.artifact, validate_task=verify_task_spec_layout)
            elif matching_legacy_state(path, plan_record) is None:
                raise ValueError("Build Plan requires '- path_schema: 1' or a matching initialized historical state")
            if unit is not None:
                result["unit_git_root"] = str(unit)
            print(json.dumps(result, ensure_ascii=True))
            return
        if args.action == "verify-task-spec":
            if not args.artifact:
                raise ValueError("verify-task-spec requires --artifact TASK_SPEC")
            content = Path(args.artifact).read_text(encoding="utf-8")
            if args.build_plan:
                build_plan = evidence_record(args.build_plan)
                plan_text = Path(build_plan["path"]).read_text(encoding="utf-8")
                if sdd_layout.structured_plan(plan_text):
                    tasks, _ = sdd_layout.proposal_layout(args.build_plan, validate_task=verify_task_spec_layout)
                    if Path(args.artifact).resolve() not in {task["path"] for task in tasks.values()}:
                        raise ValueError("Task MD is not indexed by Build Plan")
                elif not matching_historical_task(path, args.artifact, expected_plan=build_plan):
                    raise ValueError("Task MD requires a structured Build Plan or a matching initialized historical state")
            elif re.search(r"(?m)^- 主入口路径：", content) or not matching_historical_task(path, args.artifact):
                sdd_layout.task_entry_paths(content)
            print(json.dumps(verify_task_spec_layout(args.artifact), ensure_ascii=True))
            return
        if args.action == "prepare-git":
            if args.worktree:
                raise ValueError("prepare-git establishes the approved unit root before worktree creation")
            unit, _, _, _ = approved_build_plan(path, args.evidence)
            print(json.dumps(unit_git.prepare(unit, unit), ensure_ascii=True))
            return
        if args.action == "resolve-workspace":
            unit = unit_git.plan_root(path, required=False)
            requested = args.worktree or Path.cwd()
            plan = evidence_record(path)
            if unit is None:
                content = Path(plan["path"]).read_text(encoding="utf-8")
                if BUILD_PLAN_TITLE not in content and not re.search(r"\|\s*任务 ID\s*\|\s*Task MD\s*\|", content):
                    if args.artifact:
                        unit_git.reject_hardlink(args.artifact)
                    raise SystemExit(3)
                workspace, bound_state = legacy_workspace(requested, plan)
                worktree = None
            else:
                worktree = unit_git.select_worktree(unit, unit_git.discover_worktree(requested))
                bound_path = unit_git.state_path(worktree, plan["path"])
                bound_state = read(bound_path)
                if not bound_state.get("git") or bound_state.get("refs", {}).get("build_plan") != plan:
                    raise ValueError("worktree workspace belongs to a different Build Plan or revision")
                if unit_git.verify_binding(bound_state, bound_path) != worktree:
                    raise ValueError("SDD workspace belongs to a different functional-unit worktree")
                _validate_record(bound_state["refs"]["spec_approval"], "spec_approval")
                workspace = bound_path.parent
            if args.evidence and (unit is not None or "spec_approval" in bound_state):
                spec = evidence_record(args.evidence)
                if unit is not None:
                    unit_git.inside(spec["path"], unit, "Task MD", unit_paths=True)
                approved_digest = bound_state["spec_approval"]["task_specs"].get(args.value)
                if approved_digest != spec["sha256"]:
                    raise ValueError(f"task brief requires approved Task MD bytes for {args.value}")
            if args.artifact:
                unit_git.inside(args.artifact, workspace, "SDD output", unit_paths=True)
                if worktree is not None:
                    unit_git.inside(args.artifact, worktree, "SDD output", unit_paths=True)
                unit_git.reject_hardlink(args.artifact)
            print(workspace.as_posix())
            return
        if args.action == "init":
            if not args.build_plan:
                raise ValueError("init requires --build-plan")
            unit, plan, approval, receipt = approved_build_plan(args.build_plan, args.evidence)
            worktree = unit_git.select_worktree(unit, args.worktree)
            path = unit_git.verify_state_location(path, worktree, plan["path"])
            if path.exists():
                raise ValueError("state already exists")
            binding = unit_git.prepare(unit, worktree)
            unit_git.initialize_workspace(path)
        elif path.is_file():
            existing = read(path)
            if existing.get("git"):
                worktree = unit_git.verify_binding(existing, path)
                if args.worktree and worktree != Path(args.worktree).resolve():
                    raise ValueError("command worktree differs from the initialized functional-unit worktree")
            elif args.worktree:
                raise ValueError("--worktree requires an initialized functional-unit Git binding")
        else:
            raise ValueError(f"Harness state does not exist: {path}")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise SystemExit(f"Invalid SDD workspace or approval: {exc}") from None

    if args.action == "init":
        lockfile = lock(path.parent)
        try:
            if path.exists():
                raise SystemExit("state already exists")
            refs = {"build_plan": plan, "spec_approval": receipt}
            state = {"phase": "building", "status": "building_incomplete", "task_id": None,
                     "fix_round": 0, "tasks": {}, "evidence": {}, "refs": refs,
                     "spec_approval": approval, "git": binding,
                     "next_allowed_actions": NEXT["building_incomplete"]}
            write(path, state)
            root = path.parent
            write(root / "analysis-state.json", {"phase": "building", "status": "building_incomplete", "building_manifest": "building/manifest.json", "runtime_manifest": "runtime/manifest.json", "build_plan": refs.get("build_plan"), "next_allowed_actions": NEXT["building_incomplete"]})
            write(root / "building" / "manifest.json", {"phase": "building", "status": "building_incomplete", "tasks": {}, "final_review": "pending", "building_audit": "blocked", "build_plan": refs.get("build_plan"), "runtime_manifest": "runtime/manifest.json"})
            write(root / "runtime" / "manifest.json", {"phase": "runtime", "status": "blocked", "authorized_nodes": [], "steps": {}, "milestone_audit": "blocked", "final_chain_audit": "blocked", "build_plan": refs.get("build_plan"), "building_manifest": "building/manifest.json"})
            sync_manifests(root, state)
            with (root / "events.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps({"action": "init", "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")
        finally:
            lockfile.release()
        return
    lockfile=lock(path.parent)
    try:
        _main(args, path)
    finally:
        lockfile.release()

EVIDENCE_REQUIRED = {
    "task_complete", "fix_round_pending", "re_review_pending",
    "building_audit_pending", "building_audit_gate", "milestone_audit_gate", "final_chain_audit_pending",
    "runtime_finish_pending", "runtime_fix_pending",
}

def _evidence_text(records):
    chunks=[]
    for rec in records:
        try: chunks.append(Path(rec["path"]).read_text(encoding="utf-8", errors="replace"))
        except OSError: pass
    return "\n".join(chunks)

def _has_pass_verdict(text):
    return bool(re.search(r"(?im)^\s*(?:\*\*)?Verdict(?:\*\*)?\s*[:：]\s*PASS\b", text))

def _require_transition_evidence(state, current, target, records):
    text = _evidence_text(records)
    if current == "building_incomplete" and target == "task_review_pending":
        if not re.search(r"(?im)^\s*\*?\*?Status\*?\*?\s*[:：]\s*DONE(?:_WITH_CONCERNS)?\b", text):
            raise SystemExit("task review requires Implementer Status: DONE or DONE_WITH_CONCERNS")
        if not re.search(r"(?im)commit", text):
            raise SystemExit("task review requires Implementer commit evidence")
        if "TDD Evidence" not in text and "TDD exception" not in text:
            raise SystemExit("task review requires TDD evidence or an explicit TDD exception")
    if target == "task_complete":
        if not _has_pass_verdict(text):
            raise SystemExit("task_complete requires a Task Review or Re-review Verdict: PASS")
        if "CHANGES_REQUIRED" in text:
            raise SystemExit("task_complete requires resolved review evidence")
    if current == "fix_round_pending" and target == "re_review_pending":
        if not re.search(r"(?im)fix[- ]round|修复轮次", text):
            raise SystemExit("re-review requires a round-specific fix report")

def _artifact_binding(state, raw):
    candidate=str(Path(raw).resolve())
    collections=[state.get("artifact_bindings", {}), state.get("artifacts", {})]
    for collection in collections:
        items = collection.items() if isinstance(collection, dict) else enumerate(collection or [])
        for key, item in items:
            if isinstance(item, str):
                item={"path":key, "sha256":item}
            if not isinstance(item, dict): continue
            declared=item.get("path") or item.get("artifact")
            if declared and str(Path(declared).resolve()) == candidate:
                expected=item.get("sha256") or item.get("artifact_sha256")
                if expected: return {"path":candidate, "sha256":expected}
    raise SystemExit("artifact binding missing: " + candidate)

def _verify_artifact(state, raw):
    binding=_artifact_binding(state, raw)
    actual=digest(binding["path"])
    if actual != binding["sha256"]:
        raise SystemExit("artifact fingerprint changed: " + binding["path"])
    state.setdefault("artifact_verifications", {})[binding["path"]] = {"path":binding["path"], "sha256":actual}
    return state["artifact_verifications"][binding["path"]]

def verify_report_layout(report, kind):
    from runtime_harness import markdown_lines_outside_code

    required = [
        "## 1. 审查对象", "## 2. Audit 发现的问题、解决办法及完成状态",
        "## 3. 有待改进或商讨的地方", "## 4. 未作判断的部分",
        "## 5. 已核实的下一步修复方向", "## 6. 任务验收索引"
    ]
    text = Path(report).read_text(encoding="utf-8")
    heading_pattern = re.compile(r" {0,3}##[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*")
    headings = set()
    for line in markdown_lines_outside_code(text.splitlines()):
        match = heading_pattern.fullmatch(line)
        if match:
            headings.add("## " + match[1])
    missing = [h for h in required if h not in headings]
    forbidden = [
        h for h in ("## Strengths", "## Issues", "## Recommendations", "## Human Disposition")
        if h in headings
    ]
    if missing or forbidden:
        raise SystemExit(json.dumps({"missing": missing, "forbidden": forbidden}, ensure_ascii=False))
    return {"report": str(Path(report).resolve()), "kind": kind, "layout": "valid"}

def verify_task_spec_layout(task_spec):
    text = Path(task_spec).read_text(encoding="utf-8")
    if not re.search(r"(?m)^# Task .+ · .+$", text):
        raise SystemExit("task spec title must match '# Task <完整任务 ID> · <任务名称>'")
    required = [
        "# Task ",
        "- 任务 ID：", "- 父任务 ID（无则填无）：", "- 变更类型（原始／新增／替换）：",
        "- 任务目的：", "- 任务边界与明确排除项：",
        "## 输入、脚本与输出", "## 验收与验证", "## 上下游影响", "## 审批引用",
    ]
    missing = [h for h in required if h not in text]
    if missing:
        raise SystemExit(json.dumps({"missing": missing}, ensure_ascii=False))
    if "AC ID（完整任务 ID + -ACNN）" not in text:
        raise SystemExit("task spec acceptance table header missing")
    headings = ["## 输入、脚本与输出", "## 验收与验证", "## 上下游影响", "## 审批引用"]
    positions = [text.index(h) for h in headings]
    if positions != sorted(positions):
        raise SystemExit("task spec sections are out of order")
    if text.index("AC ID（完整任务 ID + -ACNN）") < positions[1]:
        raise SystemExit("task spec acceptance table must be inside 验收与验证")
    approvals = re.findall(r"(?m)^- approval_status:[ \t]*(.+)$", text[positions[-1]:])
    if len(approvals) != 1 or approvals[0].strip() not in {
        "pending", "approved", "rejected", "pending（pending / approved / rejected）"
    }:
        raise SystemExit("task spec must declare one valid approval_status")
    return {"task_spec": str(Path(task_spec).resolve()), "layout": "valid"}

def verify_build_plan_layout(build_plan):
    text = Path(build_plan).read_text(encoding="utf-8")
    required = [
        BUILD_PLAN_TITLE, "## 目标与边界", "## 源数据、算法与输出",
        "## 项目目录结构", "## 任务清单", "## Runtime 执行图",
        "## 阶段性验收节点", "## 批准",
        "| 任务 ID | Task MD | 目的与边界 | 前置任务／产物 | 相关 AC |",
        "| 运行步骤 ID | 对应任务 | 前置步骤或节点 | 输入与输出 | 可并行步骤／互斥条件 | 完成检查 |",
        "| 节点 ID | 节点目的 | 包含的运行步骤 | 前置节点 | 阶段性成果与验收条件 | 用户授权范围 |",
    ]
    missing = [h for h in required if h not in text]
    if missing:
        raise SystemExit(json.dumps({"missing": missing}, ensure_ascii=False))
    headings = ["## 目标与边界", "## 源数据、算法与输出", "## 项目目录结构", "## 任务清单", "## Runtime 执行图", "## 阶段性验收节点", "## 批准"]
    positions = [text.index(h) for h in headings]
    if positions != sorted(positions):
        raise SystemExit("build plan sections are out of order")
    forbidden = [h for h in ("Reader Spec", "## 全局约束摘录", "## Build 总体映射") if h in text]
    if forbidden:
        raise SystemExit(json.dumps({"forbidden": forbidden}, ensure_ascii=False))
    return {"build_plan": str(Path(build_plan).resolve()), "layout": "valid"}


def archive_building_cycle(root, state, runtime):
    run_id = runtime["contract"]["run_id"]
    history = {"run_id": run_id, "refs": state["refs"], "tasks": state["tasks"],
               "task_id": state["task_id"], "fix_round": state["fix_round"], "evidence": state["evidence"]}
    for key in ("building_gate", "user_acceptance", "spec_approval", "artifact_bindings", "artifacts",
                "artifact_verifications"):
        if key in state:
            history[key] = state[key]
            if key != "spec_approval" or runtime["return_stage"] == "Proposal":
                del state[key]
    if runtime["return_stage"] == "Proposal":
        import sdd_unit_git as unit_git

        root = root.resolve()
        archive = root / "history" / run_id
        if (archive.parent != root / "history"
                or unit_git.inside(archive, root, "Proposal archive", unit_paths=True) != archive):
            raise ValueError(f"Proposal archive must use its declared workspace path: {archive}")
        specs = {"build-plan": state["refs"]["build_plan"]}
        specs.update({task_id: {"path": task["task_spec_path"], "sha256": task["task_spec_sha256"]}
                      for task_id, task in state["tasks"].items()})
        snapshots = {}
        pending = {}
        for key, record in specs.items():
            snapshot = archive / (key + ".md")
            if (snapshot.parent != archive
                    or unit_git.inside(snapshot, root, "Proposal archive snapshot", unit_paths=True) != snapshot):
                raise ValueError(f"Proposal archive snapshot must use its declared workspace path: {snapshot}")
            unit_git.reject_hardlink(snapshot)
            content = Path(record["path"]).read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            if sha256 != record["sha256"]:
                raise SystemExit("approved spec changed before Proposal archival: " + record["path"])
            if not snapshot.exists():
                pending[snapshot] = content
            elif digest(snapshot) != sha256:
                raise SystemExit("Proposal archive collision: " + str(snapshot))
            snapshots[key] = {"path": str(snapshot), "sha256": sha256}
        archive.mkdir(parents=True, exist_ok=True)
        for snapshot, content in pending.items():
            with snapshot.open("xb") as stream:
                stream.write(content)
        history["spec_snapshots"] = snapshots
    state.setdefault("building_history", []).append(history)
    state.update(tasks={}, task_id=None, fix_round=0, evidence={})


def approved_build_plan(plan_path, approval_path):
    import runtime_harness as runtime
    from sdd_layout import proposal_layout
    import sdd_unit_git as unit_git

    runtime.require(approval_path, "Building requires Spec approval evidence")
    plan = evidence_record(plan_path)
    verify_build_plan_layout(plan["path"])
    unit = unit_git.plan_root(plan_path)
    content = Path(plan["path"]).read_text(encoding="utf-8")
    runtime.markdown_field(content, "decision", "approved")
    declared_tasks, _ = proposal_layout(plan["path"], validate_task=verify_task_spec_layout)
    approval, receipt = runtime.read_json(approval_path)
    if unit is not None:
        unit_git.inside(receipt["path"], unit, "Spec approval receipt", unit_paths=True)
    runtime.require(approval.get("build_plan_sha256") == plan["sha256"],
                    "Spec approval Build Plan fingerprint differs")
    tasks = runtime.objects(approval.get("task_specs"), "Spec approval Task fingerprint mapping", nonempty=True)
    for task_id, sha256 in tasks.items():
        runtime.matches(task_id, r"T\d+(?:-EXT\d+)?", "Task ID")
        runtime.matches(sha256, runtime.SHA256, "approved Task fingerprint")
    runtime.require(tasks == {key: digest(task["path"]) for key, task in declared_tasks.items()},
                    "Spec approval must bind every indexed Task MD fingerprint")
    for task in declared_tasks.values():
        runtime.markdown_field(task["path"].read_text(encoding="utf-8"), "approval_status", "approved")
    runtime.text(approval.get("user_message_ref"), "Spec approval user message reference")
    runtime.timestamp(approval.get("approved_at"))
    return unit, plan, approval, receipt


def rebind_proposal(args, state):
    import runtime_harness as runtime
    import sdd_unit_git as unit_git

    prior_runs = state.get("runtime_history", [])
    runtime.require(state["status"] == "proposal" and prior_runs
                    and prior_runs[-1]["return_stage"] == "Proposal",
                    "proposal-rebind requires a current Runtime return to Proposal")
    runtime.require(args.build_plan and args.evidence, "proposal-rebind requires --build-plan and fresh Spec approval evidence")
    binding = state.get("git")
    unit, plan, approval, receipt = approved_build_plan(args.build_plan, args.evidence)
    if binding:
        runtime.require(unit == Path(binding["unit_root"])
                        and plan["path"] == state["refs"]["build_plan"]["path"],
                        "Proposal rebind must keep the initialized functional-unit Git root and Build Plan path")
    elif unit is not None:
        raise ValueError("declared unit Git root requires a fresh unit-scoped Building init")
    ref = approval["user_message_ref"]
    prior_refs = {entry["building_audit"]["binding"]["spec_approval_ref"] for entry in prior_runs}
    decision = prior_runs[-1]["return_decisions"][-1]["decision"]
    prior_refs.add(decision["user_message_ref"])
    runtime.require(ref not in prior_refs and runtime.timestamp(approval.get("approved_at")) > runtime.timestamp(decision["decided_at"]),
                    "fresh Spec approval must follow the Proposal return and use a new user message")
    state.update(refs={"build_plan": plan, "spec_approval": receipt}, spec_approval=approval,
                 building_baseline=unit_git.head(Path(binding["worktree"])),
                 status="building_incomplete", phase="building", next_allowed_actions=NEXT["building_incomplete"])


def _main(args, path):
    import sdd_unit_git as unit_git

    state = read(path)
    binding = state.get("git")
    selected_worktree = Path(binding["worktree"]) if binding else None

    def require_overall_review(records, *, audit=None):
        import runtime_harness

        try:
            worktree = selected_worktree or unit_git.discover_worktree(path.parent.resolve())
            commit = unit_git.head(worktree)
            if not commit:
                raise ValueError("Overall Review requires a committed Git HEAD")
            runtime_harness.verify_overall_review(state, records, commit, audit=audit)
        except (ValueError, OSError) as exc:
            raise SystemExit(str(exc)) from None

    def building_records(raw, *, audit=False):
        records = evidence_records(raw)
        if binding:
            location = selected_worktree / "audits" / "building" if audit else path.parent.resolve()
            for record in records:
                try:
                    unit_git.inside(record["path"], location, "Building evidence", unit_paths=True)
                    unit_git.inside(record["path"], selected_worktree, "Building evidence", unit_paths=True)
                except ValueError as exc:
                    raise SystemExit(str(exc)) from None
        return records

    if args.action == "verify-report":
        if not args.artifact or not args.report_kind:
            raise SystemExit("verify-report requires --artifact REPORT --report-kind building|runtime")
        print(json.dumps(verify_report_layout(args.artifact, args.report_kind), ensure_ascii=False))
        return
    current = state["status"]
    root=path.parent
    if current == "proposal" and state.get("runtime_history"):
        if args.action == "status":
            print(json.dumps(state, ensure_ascii=True, indent=2))
            return
        if args.action != "proposal-rebind":
            raise SystemExit("Runtime return to Proposal requires proposal-rebind with fresh Spec approval")
    if args.action == "proposal-rebind":
        try:
            rebind_proposal(args, state)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise SystemExit(f"invalid Proposal rebind evidence: {exc}") from None
        write(path, state)
        sync_manifests(root, state)
        with (root / "events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps({"action": "proposal-rebind", "to": state["status"],
                                     "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")
        print(state["status"])
        return
    validate_evidence(state)
    if args.action.startswith("runtime-"):
        import runtime_harness

        def save_runtime(event):
            data = state["runtime"]
            target = runtime_harness.project(data)
            state.update(status=target, phase=_phase(target, runtime=True), next_allowed_actions=NEXT[target])
            data["status"] = target
            if data.get("return_stage") in {"Building", "Proposal"}:
                archive_building_cycle(root, state, data)
                state.setdefault("runtime_history", []).append(state.pop("runtime"))
            write(path, state)
            sync_manifests(root, state)
            with (root / "events.jsonl").open("a", encoding="utf-8") as events:
                events.write(json.dumps({"action": event, "to": target, "timestamp": runtime_harness.now()}) + "\n")

        try:
            result = runtime_harness.dispatch(args, state, save_runtime, verify_report_layout, state_path=path)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise SystemExit("invalid Runtime evidence or workspace: " + str(exc)) from None
        print(json.dumps(result, ensure_ascii=True))
        return
    if args.action == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2)); return
    if state.get("runtime") and args.action not in {"allowed"}:
        raise SystemExit("Runtime state transitions require scoped Runtime commands")
    if args.action == "verify":
        if not args.artifact: raise SystemExit("verify requires --artifact bound artifact")
        result=_verify_artifact(state, args.artifact)
        write(path, state)
        sync_manifests(root, state)
        print(json.dumps(result, ensure_ascii=False)); return
    if args.action == "gate":
        if current in {"building_incomplete", "task_review_pending", "fix_round_pending", "re_review_pending"}:
            if not state.get("task_id") and not state.get("tasks"):
                raise SystemExit("gate blocked: no current task evidence")
        if current == "building_audit_gate" and not state.get("evidence", {}).get("building_audit"):
            raise SystemExit("gate blocked: Building Audit evidence missing")
        if current != "building_audit_gate":
            raise SystemExit("gate requires building_audit_gate state")
        require_overall_review(state["evidence"].get("building_audit_pending", []),
                               audit=state["evidence"]["building_audit"])
        workspace = Path(args.artifact or selected_worktree or root).resolve()
        if binding and workspace != selected_worktree:
            raise SystemExit("Building gate requires the initialized functional-unit worktree")
        scripts=Path(__file__).parent
        if not args.evidence: raise SystemExit("gate requires --evidence LEDGER,AUDIT,REVIEW,ROUND")
        if Path(args.evidence).suffix.lower() == ".json" and "," not in args.evidence:
            import runtime_harness

            try:
                if binding:
                    unit_git.inside(args.evidence, path.parent.resolve(), "Building gate receipt", unit_paths=True)
                state["building_gate"] = runtime_harness.record_building_gate(
                    state, workspace, args.evidence, verify_report_layout,
                    evidence_root=path.parent.resolve() if binding else None,
                )
            except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
                raise SystemExit(f"invalid Building gate evidence: {exc}") from None
            write(path, state)
            sync_manifests(root, state)
            print("gate passed")
            return
        if binding:
            raise SystemExit("functional-unit Building gate requires a durable JSON receipt")
        parts=[x.strip() for x in args.evidence.split(",")]
        if len(parts)!=4 or not parts[0] or not parts[1] or not parts[2] or not parts[3].isdigit(): raise SystemExit("gate evidence schema requires ledger,audit,review,round")
        def bash_path(value):
            text=str(value).replace("\\", "/")
            m=re.match(r"^([A-Za-z]):/(.*)$", text)
            return "/" + m.group(1).lower() + "/" + m.group(2) if m else text
        def run_check(script, arguments, cwd):
            body=(script).read_text(encoding="utf-8")
            rel=[os.path.relpath(str(Path(x)), str(cwd)) if i < len(arguments)-1 and Path(x).is_absolute() and str(Path(x)).startswith(str(Path(cwd))) else str(x) for i,x in enumerate(arguments)]
            subprocess.run(["bash", "-c", body, "sdd-check", *rel], cwd=str(cwd), check=True)
        run_check(scripts/"check-building-gate", [str(workspace), parts[1]], workspace)
        run_check(scripts/"check-fix-loop", [parts[0], parts[2], parts[3]], workspace)
        print("gate passed"); return
    if args.action == "register-task":
        if not args.value: raise SystemExit("register-task requires TASK_ID")
        if (args.allowed_action not in {"resume_or_redispatch_implementer", "dispatch_next_task"}
                or args.allowed_action not in NEXT.get(current, [])):
            raise SystemExit("register-task requires currently allowed implementation --action")
        task_id = args.value
        if not re.fullmatch(r"T\d+(?:-EXT\d+)?", task_id): raise SystemExit("invalid task ID")
        if task_id in state.get("tasks", {}): raise SystemExit("task already registered: " + task_id)
        if not args.evidence: raise SystemExit("register-task requires --evidence TASK_MD")
        spec=evidence_record(args.evidence); parent=None if "-EXT" not in task_id else task_id.split("-EXT")[0]
        if binding:
            try:
                unit_git.inside(spec["path"], Path(binding["unit_root"]), "Task MD", unit_paths=True)
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        if state.get("spec_approval"):
            import runtime_harness
            import sdd_layout

            if state["spec_approval"]["task_specs"].get(task_id) != spec["sha256"]:
                raise SystemExit("Task MD fingerprint differs from fresh Spec approval: " + task_id)
            verify_task_spec_layout(spec["path"])
            runtime_harness.markdown_field(Path(spec["path"]).read_text(encoding="utf-8"), "approval_status", "approved")
            plan_path = Path(state["refs"]["build_plan"]["path"])
            if sdd_layout.structured_plan(plan_path.read_text(encoding="utf-8")):
                task = sdd_layout.task_expectations(plan_path).get(task_id)
                if not task or task["path"] != Path(spec["path"]).resolve():
                    raise SystemExit("Task MD path differs from the approved Build Plan: " + task_id)
        if parent and parent not in state.get("tasks", {}): raise SystemExit("parent task not registered")
        extension=parent is not None
        if extension:
            parent_task = state["tasks"][parent]
            if parent_task.get("status") != "task_complete": raise SystemExit("extension requires completed parent task")
            if not args.affected_task or not args.reusable_output or not args.invalidated_output or not args.inheritance_constraint: raise SystemExit("extension requires affected-task, reusable-output, invalidated-output and inheritance-constraint")
            if set(args.reusable_output) & set(args.invalidated_output): raise SystemExit("extension output cannot be both reusable and invalidated")
        if any(not re.fullmatch(r"T\d+(?:-EXT\d+)?", x) for x in args.affected_task): raise SystemExit("invalid affected-task")
        if extension and any(x != parent and x not in state.get("tasks", {}) for x in args.affected_task): raise SystemExit("extension affected task not registered")
        state.setdefault("tasks", {})[task_id] = {"status":"building_incomplete", "parent_task_id":parent, "task_kind":"extension" if extension else "base", "task_spec_path":spec["path"], "task_spec_sha256":spec["sha256"], "affected_tasks":args.affected_task, "reusable_outputs":args.reusable_output, "invalidated_outputs":args.invalidated_output, "inheritance_constraints":args.inheritance_constraint, "next_allowed_actions":list(NEXT["building_incomplete"])}
        state["task_id"] = task_id
        state["fix_round"] = 0
        write(path, state); sync_manifests(path.parent, state); print(task_id); return
    if args.action == "allowed":
        action=args.allowed_action or args.value
        if not action: raise SystemExit("allowed requires --action ACTION")
        allowed=NEXT.get(current, [])
        if action not in allowed: raise SystemExit(f"action not allowed: {action} (allowed: {', '.join(allowed)})")
        if action == "create_building_audit":
            require_overall_review(state["evidence"].get("building_audit_pending", []))
        print(json.dumps({"allowed":True,"action":action,"state":current},ensure_ascii=False)); return
    if not (args.to or args.value): raise SystemExit("transition requires --to STATE")
    target = args.to or args.value
    if target in PHASE_STATUSES["runtime"] | PHASE_STATUSES["runtime_audit"] | PHASE_STATUSES["runtime_finish"]:
        raise SystemExit("Runtime transitions require runtime-init and scoped Runtime commands")
    if args.allowed_action:
        if args.allowed_action not in NEXT.get(current, []):
            raise SystemExit("action not allowed: " + args.allowed_action)
        if target not in ACTION_TARGETS.get(args.allowed_action, set()):
            raise SystemExit("action does not map to target: " + args.allowed_action)
    if target not in STATES.get(current, set()):
        raise SystemExit(f"blocked transition: {current} -> {target}")
    if target in EVIDENCE_REQUIRED and not args.evidence:
        if target == "building_audit_pending":
            raise SystemExit("Building Audit requires one independent Overall Review report")
        raise SystemExit("transition requires evidence: " + target)
    if target == "final_review_pending":
        tasks = state.get("tasks", {})
        approved = state.get("spec_approval", {}).get("task_specs")
        if (not tasks or any(task.get("status") != "task_complete" for task in tasks.values())
                or (approved is not None and tasks.keys() != approved.keys())):
            raise SystemExit("Final Review requires all approved tasks to be complete")
    active_task = state.get("tasks", {}).get(state.get("task_id"), {})
    starting_task_review = target == "task_review_pending" and (
        current == "building_incomplete" or active_task.get("status") == "building_incomplete"
    )
    records = building_records(args.evidence, audit=target == "building_audit_gate") if args.evidence else []
    if target == "building_audit_pending":
        require_overall_review(records)
    if target == "building_audit_gate":
        require_overall_review(state["evidence"].get("building_audit_pending", []), audit=records)
        if binding:
            try:
                verify_report_layout(records[0]["path"], "building")
            except SystemExit as exc:
                raise SystemExit(f"Building Audit report layout: {exc}") from None
    if records and target in EVIDENCE_REQUIRED:
        candidate_records = records
        if target == "fix_round_pending" and "CHANGES_REQUIRED" not in _evidence_text(candidate_records):
            raise SystemExit("fix round requires CHANGES_REQUIRED evidence")
        if target == "task_complete" and "CHANGES_REQUIRED" in _evidence_text(candidate_records):
            raise SystemExit("task_complete requires resolved review evidence")
    if target in {"task_review_pending", "task_complete", "re_review_pending"}:
        if not args.evidence:
            raise SystemExit("transition requires role-specific evidence: " + target)
        _require_transition_evidence(state, "building_incomplete" if starting_task_review else current,
                                     target, records)
    if target == "task_complete":
        task=state.get("tasks", {}).get(state.get("task_id"), {})
        if task.get("review_status") == "CHANGES_REQUIRED":
            raise SystemExit("task_complete blocked by CHANGES_REQUIRED review")
    if target == "fix_round_pending":
        if not state.get("task_id"): raise SystemExit("fix round requires current task")
        if int(state.get("fix_round", 0)) >= 5: raise SystemExit("fix round limit reached")
        state["fix_round"] = int(state.get("fix_round", 0)) + 1
    if target == "re_review_pending" and current == "fix_round_pending":
        if not args.evidence: raise SystemExit("re-review requires fix evidence")
    if records:
        state.setdefault("evidence", {})[target] = records
        if target == "building_audit_gate": state["evidence"]["building_audit"] = records
    state["status"] = target
    state["phase"] = _phase(target)
    state["next_allowed_actions"] = NEXT.get(target,[])
    task_id = state.get("task_id")
    if (target in {"task_review_pending", "fix_round_pending", "re_review_pending", "task_complete",
                   "user_decision_pending"} and task_id in state.get("tasks", {})):
        task = state["tasks"][task_id]
        task["status"] = target
        task["next_allowed_actions"] = list(NEXT.get(target, []))
        if target == "fix_round_pending": task["fix_round"] = state["fix_round"]
        if starting_task_review:
            task.setdefault("building_chain", {})["implementation"] = records
        if target == "task_complete":
            task.setdefault("building_chain", {})["review"] = records
        if target == "fix_round_pending":
            task.setdefault("building_chain", {}).setdefault("fix_rounds", []).append({"findings": records})
        if target == "re_review_pending":
            rounds = task.setdefault("building_chain", {}).setdefault("fix_rounds", [])
            if not rounds:
                rounds.append({"findings": state["evidence"].get("fix_round_pending", [])})
            rounds[-1]["implementation"] = records
    write(path, state)
    sync_manifests(root, state)
    if (root/"analysis-state.json").exists():
        a=read(root/"analysis-state.json"); a.update({"phase":state.get("phase"),"status":target,"next_allowed_actions":state["next_allowed_actions"]}); write(root/"analysis-state.json",a)
    for manifest in (root/"building"/"manifest.json",root/"runtime"/"manifest.json"):
        if manifest.exists():
            m=read(manifest); m["status"]=target if m.get("phase")==state.get("phase") else m.get("status"); write(manifest,m)
    event = path.parent / "events.jsonl"
    with event.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"from": current, "to": target, "timestamp": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
    print(f"{current} -> {target}")

if __name__ == "__main__": main()
