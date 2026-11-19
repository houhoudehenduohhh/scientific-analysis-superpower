#!/usr/bin/env python3
"""Deterministic SDD phase harness with three manifest support."""
import argparse
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

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

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
    ap.add_argument("action", choices=["init", "status", "transition", "allowed"])
    ap.add_argument("value", nargs="?")
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
    state = read(path)
    current = state["status"]
    if args.action == "status":
        print(json.dumps(state, ensure_ascii=False, indent=2)); return
    if not args.value: raise SystemExit("transition/allowed requires target state")
    target = args.value
    if target not in STATES.get(current, set()):
        raise SystemExit(f"blocked transition: {current} -> {target}")
    if args.action == "allowed":
        print("allowed"); return
    state["status"] = target
    state["next_allowed_actions"] = [] if target in {"user_decision_pending", "runtime_finish_pending"} else ["dispatch_next_allowed_action"]
    write(path, state)
    print(f"{current} -> {target}")

if __name__ == "__main__": main()
