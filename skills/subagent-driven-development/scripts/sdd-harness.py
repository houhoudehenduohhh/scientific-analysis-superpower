#!/usr/bin/env python3
"""Deterministic SDD phase harness with three manifest support."""
import argparse
import hashlib
import json
import os
import tempfile
import re
import subprocess
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

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
 "user_decision_pending":["wait_for_user_decision"]}
PHASE_STATUSES = {
 "proposal":{"proposal"},
 "building":{"building_incomplete","task_review_pending","fix_round_pending","re_review_pending","task_complete","final_review_pending"},
 "building_audit":{"building_audit_pending","building_audit_gate"},
 "runtime":{"runtime_authorized","runtime_step_pending","runtime_step_review_pending","runtime_fix_pending"},
 "runtime_audit":{"milestone_audit_pending","milestone_audit_gate","final_chain_audit_pending"},
 "runtime_finish":{"runtime_finish_pending"}}
ACTION_TARGETS = {
 "resume_or_redispatch_proposer":{"building_incomplete"}, "resume_or_redispatch_implementer":{"building_incomplete"},
 "dispatch_task_reviewer":{"task_review_pending"}, "dispatch_fix_agent":{"fix_round_pending"}, "dispatch_reviewer":{"re_review_pending"},
 "dispatch_next_task":{"task_review_pending"}, "dispatch_final_review":{"final_review_pending"}, "create_building_audit":{"building_audit_pending"},
 "wait_for_user_decision":{"building_audit_gate","milestone_audit_gate","user_decision_pending"},
 "execute_runtime_step":{"runtime_step_pending"}, "dispatch_runtime_step_reviewer":{"runtime_step_review_pending"},
 "retry_runtime_step":{"runtime_step_pending"}, "return_building":{"building_incomplete"}, "return_proposal":{"proposal"},
 "dispatch_milestone_audit":{"milestone_audit_pending"}, "dispatch_final_chain_audit":{"final_chain_audit_pending"}, "dispatch_runtime_finish":{"runtime_finish_pending"}}

def _phase(status):
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
        self.token = secrets.token_hex(16)
        self.owned = False

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            stale = False
            try:
                old = json.loads(self.path.read_text(encoding="utf-8"))
                os.kill(int(old["pid"]), 0)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                stale = True
            if stale:
                try: self.path.unlink()
                except FileNotFoundError: pass
            else:
                raise SystemExit("harness locked by another process")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "token": self.token, "created_at": datetime.now(timezone.utc).isoformat()}, f)
            self.owned = True
        except FileExistsError:
            raise SystemExit("harness locked by another process")
        return self

    def release(self):
        if not self.owned: return
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("pid") == os.getpid() and current.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        self.owned = False

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

def _validate_record(rec, label):
    if not isinstance(rec, dict) or not rec.get("path") or not re.fullmatch(r"[0-9a-f]{64}", str(rec.get("sha256", ""))):
        raise SystemExit("invalid evidence schema: " + label)
    p=Path(rec["path"])
    if not p.is_file() or digest(p) != rec["sha256"]:
        raise SystemExit("evidence fingerprint changed: " + str(p))

def validate_evidence(state):
    refs = state.get("refs", {})
    for name in ("reader_spec", "build_plan"):
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
    root=Path(root); refs=state.get("refs", {}); status=state.get("status"); phase=_phase(status)
    view={"reader_spec":refs.get("reader_spec"), "reader_spec_sha256":refs.get("reader_spec",{}).get("sha256") if refs.get("reader_spec") else None, "build_plan":refs.get("build_plan"), "build_plan_sha256":refs.get("build_plan",{}).get("sha256") if refs.get("build_plan") else None}
    write(root/"analysis-state.json", {"phase":phase,"status":status,**view,"building_manifest":"building/manifest.json","runtime_manifest":"runtime/manifest.json","next_allowed_actions":list(NEXT.get(status, []))})
    bp=read(root/"building/manifest.json") if (root/"building/manifest.json").exists() else {}
    bp.update({"phase":"building","status":status if phase in {"building", "building_audit"} else bp.get("status","building_audit_gate"),**view,"runtime_manifest":"runtime/manifest.json","tasks":state.get("tasks",bp.get("tasks",{})),"evidence":state.get("evidence",bp.get("evidence",{})),"user_acceptance":state.get("user_acceptance",bp.get("user_acceptance"))})
    write(root/"building/manifest.json",bp)
    rp=read(root/"runtime/manifest.json") if (root/"runtime/manifest.json").exists() else {}
    rp.update({"phase":"runtime","status":status if phase in {"runtime", "runtime_audit", "runtime_finish"} else rp.get("status","blocked"),**view,"building_manifest":"building/manifest.json","evidence":state.get("evidence",rp.get("evidence",{})),"user_acceptance":state.get("user_acceptance",rp.get("user_acceptance"))})
    write(root/"runtime/manifest.json",rp)
    reconcile_manifests(root)

def reconcile_manifests(root):
    root=Path(root); a=read(root/"analysis-state.json"); b=read(root/"building/manifest.json"); r=read(root/"runtime/manifest.json")
    for key in ("reader_spec_sha256","build_plan_sha256"):
        if a.get(key)!=b.get(key) or a.get(key)!=r.get(key): raise SystemExit("manifest reference mismatch: "+key)
    if a.get("building_manifest")!="building/manifest.json" or a.get("runtime_manifest")!="runtime/manifest.json": raise SystemExit("manifest link mismatch")
    if a.get("phase") in {"runtime", "runtime_audit", "runtime_finish"} and r.get("status")!=a.get("status"): raise SystemExit("runtime manifest status mismatch")
    if a.get("phase") in {"proposal", "building", "building_audit"} and b.get("status")!=a.get("status"): raise SystemExit("building manifest status mismatch")
    if b.get("phase") != "building" or r.get("phase") != "runtime": raise SystemExit("manifest phase mismatch")

def main():
    # Accept the documented command-first form as well as the historical
    # STATE COMMAND form used by existing SDD workspaces.
    commands={"init", "status", "transition", "allowed", "verify", "register-task", "gate"}
    if len(sys.argv) > 2 and sys.argv[1] in commands:
        sys.argv[1], sys.argv[2] = sys.argv[2], sys.argv[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("action", choices=["init", "status", "transition", "allowed", "verify", "register-task", "gate"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--artifact", default="")
    ap.add_argument("--to")
    ap.add_argument("--action", dest="allowed_action")
    ap.add_argument("--user-accepted", action="store_true")
    ap.add_argument("--reader-spec", default="")
    ap.add_argument("--build-plan", default="")
    ap.add_argument("--affected-task", action="append", default=[])
    ap.add_argument("--reusable-output", action="append", default=[])
    ap.add_argument("--invalidated-output", action="append", default=[])
    ap.add_argument("--inheritance-constraint", action="append", default=[])
    args = ap.parse_args()
    path = Path(args.state)
    if args.action == "init":
        lockfile=lock(path.parent)
        try:
            if path.exists(): raise SystemExit("state already exists")
            if not args.reader_spec or not args.build_plan:
                raise SystemExit("init requires --reader-spec and --build-plan")
            refs={"reader_spec": evidence_record(args.reader_spec), "build_plan": evidence_record(args.build_plan)}
            state={"phase": "building", "status": "building_incomplete", "task_id": None, "fix_round": 0, "tasks": {}, "evidence": {}, "refs": refs, "next_allowed_actions": NEXT["building_incomplete"]}
            write(path, state)
            root = path.parent
            write(root / "analysis-state.json", {"phase": "building", "status": "building_incomplete", "building_manifest": "building/manifest.json", "runtime_manifest": "runtime/manifest.json", "reader_spec": refs.get("reader_spec"), "build_plan": refs.get("build_plan"), "next_allowed_actions": NEXT["building_incomplete"]})
            write(root / "building" / "manifest.json", {"phase": "building", "status": "building_incomplete", "tasks": {}, "final_review": "pending", "building_audit": "blocked", "reader_spec": refs.get("reader_spec"), "build_plan": refs.get("build_plan"), "runtime_manifest": "runtime/manifest.json"})
            write(root / "runtime" / "manifest.json", {"phase": "runtime", "status": "blocked", "authorized_nodes": [], "steps": {}, "milestone_audit": "blocked", "final_chain_audit": "blocked", "reader_spec": refs.get("reader_spec"), "build_plan": refs.get("build_plan"), "building_manifest": "building/manifest.json"})
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
    "building_audit_gate", "milestone_audit_gate", "final_chain_audit_pending",
    "runtime_finish_pending", "runtime_fix_pending",
}

def _evidence_text(records):
    chunks=[]
    for rec in records:
        try: chunks.append(Path(rec["path"]).read_text(encoding="utf-8", errors="replace"))
        except OSError: pass
    return "\n".join(chunks)

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

def _main(args, path):
    state = read(path)
    validate_evidence(state)
    current = state["status"]
    root=path.parent
    if args.action == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2)); return
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
        workspace=Path(args.artifact or root)
        scripts=Path(__file__).parent
        if not args.evidence: raise SystemExit("gate requires --evidence LEDGER,AUDIT,REVIEW,ROUND")
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
        if args.allowed_action not in NEXT.get(current, []): raise SystemExit("register-task requires currently allowed --action")
        task_id = args.value
        if not re.fullmatch(r"T\d+(?:-EXT\d+)?", task_id): raise SystemExit("invalid task ID")
        if task_id in state.get("tasks", {}): raise SystemExit("task already registered: " + task_id)
        if not args.evidence: raise SystemExit("register-task requires --evidence TASK_MD")
        spec=evidence_record(args.evidence); parent=None if "-EXT" not in task_id else task_id.split("-EXT")[0]
        if parent and parent not in state.get("tasks", {}): raise SystemExit("parent task not registered")
        extension=parent is not None
        if extension:
            parent_task = state["tasks"][parent]
            if parent_task.get("status") != "task_complete": raise SystemExit("extension requires completed parent task")
            if not args.affected_task or not args.reusable_output or not args.invalidated_output or not args.inheritance_constraint: raise SystemExit("extension requires affected-task, reusable-output, invalidated-output and inheritance-constraint")
            if set(args.reusable_output) & set(args.invalidated_output): raise SystemExit("extension output cannot be both reusable and invalidated")
        if any(not re.fullmatch(r"T\d+(?:-EXT\d+)?", x) for x in args.affected_task): raise SystemExit("invalid affected-task")
        if extension and any(x != parent and x not in state.get("tasks", {}) for x in args.affected_task): raise SystemExit("extension affected task not registered")
        state.setdefault("tasks", {})[task_id] = {"status":"building_incomplete", "parent_task_id":parent, "task_kind":"extension" if extension else "base", "task_spec_path":spec["path"], "task_spec_sha256":spec["sha256"], "affected_tasks":args.affected_task, "reusable_outputs":args.reusable_output, "invalidated_outputs":args.invalidated_output, "inheritance_constraints":args.inheritance_constraint, "next_allowed_actions":["dispatch_implementer"]}
        state["task_id"] = task_id
        write(path, state); sync_manifests(path.parent, state); print(task_id); return
    if args.action == "allowed":
        action=args.allowed_action or args.value
        if not action: raise SystemExit("allowed requires --action ACTION")
        allowed=NEXT.get(current, [])
        if action not in allowed: raise SystemExit(f"action not allowed: {action} (allowed: {', '.join(allowed)})")
        print(json.dumps({"allowed":True,"action":action,"state":current},ensure_ascii=False)); return
    if not (args.to or args.value): raise SystemExit("transition requires --to STATE")
    target = args.to or args.value
    if args.allowed_action:
        if args.allowed_action not in NEXT.get(current, []):
            raise SystemExit("action not allowed: " + args.allowed_action)
        if target not in ACTION_TARGETS.get(args.allowed_action, set()):
            raise SystemExit("action does not map to target: " + args.allowed_action)
    if target not in STATES.get(current, set()):
        raise SystemExit(f"blocked transition: {current} -> {target}")
    if target in EVIDENCE_REQUIRED and not args.evidence:
        raise SystemExit("transition requires evidence: " + target)
    if args.evidence and target in EVIDENCE_REQUIRED:
        candidate_records=evidence_records(args.evidence)
        if target == "fix_round_pending" and "CHANGES_REQUIRED" not in _evidence_text(candidate_records):
            raise SystemExit("fix round requires CHANGES_REQUIRED evidence")
        if target == "task_complete" and "CHANGES_REQUIRED" in _evidence_text(candidate_records):
            raise SystemExit("task_complete requires resolved review evidence")
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
    if target == "runtime_authorized":
        if current != "building_audit_gate": raise SystemExit("runtime authorization requires Building Audit gate")
        evidence = state.get("evidence", {})
        if not evidence.get("building_audit"):
            raise SystemExit("blocked: Building Audit evidence missing")
        acceptance = state.get("user_acceptance", {})
        audit_hash = hashlib.sha256(json.dumps(evidence["building_audit"], sort_keys=True).encode()).hexdigest()
        if acceptance.get("accepted") and acceptance.get("building_audit_sha256") != audit_hash:
            raise SystemExit("blocked: durable user acceptance is stale")
        if not args.user_accepted and not acceptance.get("accepted"):
            raise SystemExit("blocked: durable user acceptance required")
        if args.user_accepted:
            state["user_acceptance"]={"accepted":True,"accepted_at":datetime.now(timezone.utc).isoformat(),"accepted_state":current,"building_audit":evidence["building_audit"],"building_audit_sha256":audit_hash}
    if args.evidence:
        records = evidence_records(args.evidence)
        state.setdefault("evidence", {})[target] = records
        if target == "building_audit_gate": state["evidence"]["building_audit"] = records
    state["status"] = target
    state["phase"] = _phase(target)
    state["next_allowed_actions"] = NEXT.get(target,[])
    task_id = state.get("task_id")
    if task_id and task_id in state.get("tasks", {}):
        task = state["tasks"][task_id]
        task["status"] = target
        task["next_allowed_actions"] = list(NEXT.get(target, []))
        if target == "fix_round_pending": task["fix_round"] = state["fix_round"]
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
