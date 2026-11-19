#!/usr/bin/env python3
"""Deterministic SDD phase harness with three manifest support."""
import argparse
import hashlib
import json
import os
import tempfile
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STATES = {
    "building_incomplete": {"task_review_pending"},
    "task_review_pending": {"task_complete", "fix_round_pending"},
    "fix_round_pending": {"re_review_pending", "user_decision_pending"},
    "re_review_pending": {"task_complete", "fix_round_pending", "user_decision_pending"},
    "task_complete": {"task_review_pending", "final_review_pending"},
    "final_review_pending": {"building_audit_pending"},
    "building_audit_pending": {"building_audit_gate"},
    "building_audit_gate": {"runtime_authorized"},
    "user_decision_pending": set(),
    "runtime_authorized": {"runtime_step_pending"},
    "runtime_step_pending": {"runtime_step_review_pending"},
    "runtime_step_review_pending": {"runtime_fix_pending", "milestone_audit_pending"},
    "runtime_fix_pending": {"runtime_step_pending", "user_decision_pending"},
    "milestone_audit_pending": {"milestone_audit_gate"},
    "milestone_audit_gate": {"runtime_step_pending", "final_chain_audit_pending"},
    "final_chain_audit_pending": {"runtime_finish_pending"},
    "runtime_finish_pending": set(),
}
NEXT = {
 "building_incomplete":["dispatch_implementer"], "task_review_pending":["dispatch_task_reviewer"],
 "fix_round_pending":["dispatch_fix_agent"], "re_review_pending":["dispatch_reviewer"],
 "task_complete":["dispatch_next_task","dispatch_final_review"], "final_review_pending":["dispatch_final_review"],
 "building_audit_pending":["create_building_audit"], "building_audit_gate":["wait_for_user_decision"],
 "runtime_authorized":["execute_runtime_step"], "runtime_step_pending":["execute_runtime_step"],
 "runtime_step_review_pending":["dispatch_runtime_step_reviewer"], "runtime_fix_pending":["retry_runtime_step","return_building","return_proposal"],
 "milestone_audit_pending":["dispatch_milestone_audit"], "milestone_audit_gate":["wait_for_user_decision"],
 "final_chain_audit_pending":["dispatch_final_chain_audit"], "runtime_finish_pending":["dispatch_runtime_finish"],
 "user_decision_pending":["wait_for_user_decision"]}

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def digest(path):
    h=hashlib.sha256();
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()

def lock(root):
    p=Path(root)/".harness.lock"
    if p.exists():
        try:
            pid=int(p.read_text(encoding="ascii").strip()); os.kill(pid, 0)
        except (ValueError, OSError):
            p.unlink(missing_ok=True)
        else:
            raise SystemExit("harness locked by another process")
    try:
        fd=os.open(p, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
    except FileExistsError: raise SystemExit("harness locked by another process")
    return p

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

def validate_evidence(state):
    for ref in state.get("refs", {}).values():
        if isinstance(ref, dict) and (not Path(ref["path"]).is_file() or digest(ref["path"]) != ref.get("sha256")):
            raise SystemExit("reference fingerprint changed: " + str(ref.get("path")))
    for records in state.get("evidence", {}).values():
        if isinstance(records, dict): records=[records]
        for rec in records or []:
            if isinstance(rec, str): continue
            p=Path(rec["path"])
            if not p.is_file() or digest(p) != rec.get("sha256"):
                raise SystemExit("evidence fingerprint changed: " + str(p))

def sync_manifests(root, state):
    refs=state.get("refs", {})
    common={"reader_spec":refs.get("reader_spec"), "build_plan":refs.get("build_plan"), "building_manifest":"building/manifest.json", "runtime_manifest":"runtime/manifest.json"}
    write(root/"analysis-state.json", {"phase":state.get("phase"), "status":state.get("status"), **common, "next_allowed_actions":state.get("next_allowed_actions", [])})
    bp=read(root/"building/manifest.json") if (root/"building/manifest.json").exists() else {}
    bp.update({"phase":"building", "status":state.get("status"), "reader_spec":refs.get("reader_spec"), "build_plan":refs.get("build_plan"), "runtime_manifest":"runtime/manifest.json"})
    write(root/"building/manifest.json", bp)
    rp=read(root/"runtime/manifest.json") if (root/"runtime/manifest.json").exists() else {}
    rp.update({"phase":"runtime", "reader_spec":refs.get("reader_spec"), "build_plan":refs.get("build_plan"), "building_manifest":"building/manifest.json"})
    write(root/"runtime/manifest.json", rp)

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
        except BaseException:
            lockfile.unlink(missing_ok=True); raise
        refs={}
        for name, raw in (("reader_spec",args.reader_spec),("build_plan",args.build_plan)):
            if raw: refs[name]=evidence_record(raw)
        state={"phase": "building", "status": "building_incomplete", "task_id": None, "fix_round": 0, "evidence": {}, "refs": refs, "next_allowed_actions": NEXT["building_incomplete"]}
        write(path, state)
        root = path.parent
        write(root / "analysis-state.json", {"phase": "building", "status": "building_incomplete", "building_manifest": "building/manifest.json", "runtime_manifest": "runtime/manifest.json", "reader_spec": refs.get("reader_spec"), "build_plan": refs.get("build_plan"), "next_allowed_actions": NEXT["building_incomplete"]})
        write(root / "building" / "manifest.json", {"phase": "building", "status": "building_incomplete", "tasks": {}, "final_review": "pending", "building_audit": "blocked", "reader_spec": refs.get("reader_spec"), "build_plan": refs.get("build_plan"), "runtime_manifest": "runtime/manifest.json"})
        write(root / "runtime" / "manifest.json", {"phase": "runtime", "status": "blocked", "authorized_nodes": [], "steps": {}, "milestone_audit": "blocked", "final_chain_audit": "blocked", "reader_spec": refs.get("reader_spec"), "build_plan": refs.get("build_plan"), "building_manifest": "building/manifest.json"})
        with (root / "events.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps({"action": "init", "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")
        lockfile.unlink(missing_ok=True)
        return
    lockfile=lock(path.parent)
    try:
        _main(args, path)
    finally:
        lockfile.unlink(missing_ok=True)

def _main(args, path):
    state = read(path)
    validate_evidence(state)
    current = state["status"]
    root=path.parent
    if args.action == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2)); return
    if args.action == "verify":
        print(json.dumps(evidence_records(args.artifact or args.evidence), ensure_ascii=False)); return
    if args.action == "gate":
        if current in {"building_incomplete", "task_review_pending", "fix_round_pending", "re_review_pending"}:
            if not state.get("task_id") and not state.get("tasks"):
                raise SystemExit("gate blocked: no current task evidence")
        if current == "building_audit_gate" and not state.get("evidence", {}).get("building_audit"):
            raise SystemExit("gate blocked: Building Audit evidence missing")
        workspace=Path(args.artifact or root)
        scripts=Path(__file__).parent
        if args.evidence:
            parts=args.evidence.split(",")
            if len(parts) >= 1:
                audit=parts[1] if len(parts) > 1 else ""
                subprocess.run(["bash", str(scripts/"check-building-gate"), str(workspace), audit], check=True)
            if len(parts) >= 4:
                subprocess.run(["bash", str(scripts/"check-fix-loop"), *parts[2:5]], check=True)
        print("gate passed"); return
    if args.action == "register-task":
        if not args.value: raise SystemExit("register-task requires TASK_ID")
        task_id = args.value
        if not re.fullmatch(r"T\d+(?:-EXT\d+)?", task_id):
            raise SystemExit("invalid task ID")
        if not args.evidence: raise SystemExit("register-task requires --evidence TASK_MD")
        spec=Path(args.evidence)
        if not spec.is_file(): raise SystemExit("missing Task MD")
        parent=None if "-EXT" not in task_id else task_id.split("-EXT")[0]
        if parent and parent not in state.get("tasks", {}): raise SystemExit("parent task not registered")
        extension=parent is not None
        if extension and (not args.affected_task or not args.reusable_output or not args.invalidated_output or not args.inheritance_constraint):
            raise SystemExit("extension requires affected-task, reusable-output, invalidated-output and inheritance-constraint")
        state.setdefault("tasks", {})[task_id] = {"status": "building_incomplete", "parent_task_id": parent, "task_kind": "extension" if extension else "base", "task_spec_sha256": digest(spec), "affected_tasks": args.affected_task, "reusable_outputs": args.reusable_output, "invalidated_outputs": args.invalidated_output, "inheritance_constraints": args.inheritance_constraint, "next_allowed_actions": ["dispatch_implementer"]}
        state["task_id"] = task_id
        write(path.parent/"building"/"manifest.json", {**read(path.parent/"building"/"manifest.json"), "tasks":state["tasks"]})
        write(path, state); sync_manifests(path.parent, state); print(task_id); return
    if args.action == "allowed":
        action=args.allowed_action or args.value
        if not action: raise SystemExit("allowed requires --action ACTION")
        allowed=NEXT.get(current, [])
        if action not in allowed: raise SystemExit(f"action not allowed: {action} (allowed: {', '.join(allowed)})")
        print(json.dumps({"allowed":True,"action":action,"state":current},ensure_ascii=False)); return
    if not (args.to or args.value): raise SystemExit("transition requires --to STATE")
    target = args.to or args.value
    if target not in STATES.get(current, set()):
        raise SystemExit(f"blocked transition: {current} -> {target}")
    if target == "runtime_authorized":
        evidence = state.get("evidence", {})
        if not evidence.get("building_audit"):
            raise SystemExit("blocked: Building Audit evidence missing")
        if not args.user_accepted and not state.get("user_acceptance", {}).get("accepted"):
            raise SystemExit("blocked: durable user acceptance required")
        if args.user_accepted:
            state["user_acceptance"]={"accepted":True,"accepted_at":datetime.now(timezone.utc).isoformat(),"accepted_state":current,"building_audit":evidence["building_audit"]}
    if args.evidence:
        state.setdefault("evidence", {})[target] = evidence_records(args.evidence)
    state["status"] = target
    state["next_allowed_actions"] = NEXT.get(target,[])
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
