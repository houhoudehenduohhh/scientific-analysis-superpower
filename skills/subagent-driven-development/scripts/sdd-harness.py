#!/usr/bin/env python3
"""Small deterministic state machine for SDD Building gates."""
import argparse
import json
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
    "runtime_authorized": set(),
}

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
    write(path, state)
    print(f"{current} -> {target}")

if __name__ == "__main__": main()
