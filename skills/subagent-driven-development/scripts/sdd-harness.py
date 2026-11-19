#!/usr/bin/env python3
"""Deterministic SDD phase harness with three manifest support."""
import argparse
import hashlib
import json
import os
import tempfile
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state")
    ap.add_argument("action", choices=["init", "status", "transition", "allowed", "verify", "register-task", "gate"])
    ap.add_argument("value", nargs="?")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--user-accepted", action="store_true")
    args = ap.parse_args()
    path = Path(args.state)
    if args.action == "init":
        if path.exists(): raise SystemExit("state already exists")
        write(path, {"phase": "building", "status": "building_incomplete", "task_id": None, "fix_round": 0, "evidence": {}})
        root = path.parent
        write(root / "analysis-state.json", {"phase": "building", "status": "building_incomplete", "building_manifest": "building/manifest.json", "runtime_manifest": "runtime/manifest.json", "next_allowed_actions": ["dispatch_implementer"]})
        write(root / "building" / "manifest.json", {"phase": "building", "status": "building_incomplete", "tasks": {}, "final_review": "pending", "building_audit": "blocked", "evidence": {}})
        write(root / "runtime" / "manifest.json", {"phase": "runtime", "status": "blocked", "authorized_nodes": [], "steps": {}, "milestone_audit": "blocked", "final_chain_audit": "blocked"})
        with (root / "events.jsonl").open("a", encoding="utf-8") as f: f.write(json.dumps({"action": "init", "timestamp": datetime.now(timezone.utc).isoformat()}) + "\n")
        return
    lockfile=lock(path.parent)
    try:
        _main(args, path)
    finally:
        lockfile.unlink(missing_ok=True)

def _main(args, path):
    state = read(path)
    current = state["status"]
    root=path.parent
    if args.action == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2)); return
    if args.action == "verify":
        paths = [Path(x) for x in args.evidence.split(",") if x]
        missing = [str(x) for x in paths if not x.is_file()]
        if missing: raise SystemExit("missing evidence: " + ", ".join(missing))
        print(json.dumps({str(x):digest(x) for x in paths}, ensure_ascii=False)); return
    if args.action == "gate":
        if current in {"building_incomplete", "task_review_pending", "fix_round_pending", "re_review_pending"}:
            if not state.get("task_id") and not state.get("tasks"):
                raise SystemExit("gate blocked: no current task evidence")
        if current == "building_audit_gate" and not state.get("evidence", {}).get("building_audit"):
            raise SystemExit("gate blocked: Building Audit evidence missing")
        print("gate passed"); return
    if args.action == "register-task":
        if not args.value: raise SystemExit("register-task requires TASK_ID")
        task_id = args.value
        if not (task_id.startswith("T") and task_id[1:].replace("-EXT", "").isdigit()):
            raise SystemExit("invalid task ID")
        spec=Path(args.evidence) if args.evidence else None
        if spec and not spec.is_file(): raise SystemExit("missing Task MD")
        parent=None if "-EXT" not in task_id else task_id.split("-EXT")[0]
        if parent and parent not in state.get("tasks", {}): raise SystemExit("parent task not registered")
        state.setdefault("tasks", {})[task_id] = {"status": "building_incomplete", "parent_task_id": parent, "task_spec_sha256": digest(spec) if spec else None, "affected_outputs": []}
        write(path.parent/"building"/"manifest.json", {**read(path.parent/"building"/"manifest.json"), "tasks":state["tasks"]})
        write(path, state); print(task_id); return
    if not args.value: raise SystemExit("transition/allowed requires target state")
    target = args.value
    if target not in STATES.get(current, set()):
        raise SystemExit(f"blocked transition: {current} -> {target}")
    if target == "runtime_authorized":
        evidence = state.get("evidence", {})
        if not args.user_accepted or not evidence.get("building_audit"):
            raise SystemExit("blocked: runtime authorization requires user acceptance and Building Audit evidence")
    if args.evidence:
        paths = [Path(x) for x in args.evidence.split(",") if x]
        missing = [str(x) for x in paths if not x.is_file()]
        if missing: raise SystemExit("missing evidence: " + ", ".join(missing))
        state.setdefault("evidence", {})[target] = [str(x) for x in paths]
    if args.action == "allowed":
        print(json.dumps({"allowed":True,"actions":NEXT.get(target,[])},ensure_ascii=False)); return
    state["status"] = target
    state["next_allowed_actions"] = NEXT.get(target,[])
    write(path, state)
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
