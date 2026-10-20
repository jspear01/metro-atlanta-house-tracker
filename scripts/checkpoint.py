#!/usr/bin/env python3
"""
Checkpoint Harness CLI for Metro Atlanta Real Estate Price Tracker.
Manages session state, task tracking, run history, and synchronization with PROJECT_STATE.md.
"""

import os
import sys
import json
import datetime
from pathlib import Path

# Resolve base directories
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
STATE_DIR = PROJECT_ROOT / ".state"
CHECKPOINT_FILE = STATE_DIR / "checkpoint.json"
RUN_HISTORY_FILE = STATE_DIR / "run_history.log"
PROJECT_STATE_MD = PROJECT_ROOT / "PROJECT_STATE.md"


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)


def log_history(action: str, details: str = ""):
    ensure_state_dir()
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry = f"[{timestamp}] ACTION: {action} | DETAILS: {details}\n"
    with open(RUN_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def get_default_checkpoint():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "project_name": "Metro Atlanta Real Estate Price Tracker",
        "version": "1.0.0",
        "created_at": now,
        "last_updated": now,
        "current_phase": "Phase 1: Persistent Harness & Environment Setup",
        "milestones": [
            {
                "id": "M1",
                "title": "Persistent Checkpoint Harness Protocol",
                "status": "in_progress",
                "tasks": [
                    {"id": "T1.1", "name": "Create directory layout and .state harness", "status": "in_progress"},
                    {"id": "T1.2", "name": "Implement scripts/checkpoint.py state manager", "status": "in_progress"},
                    {"id": "T1.3", "name": "Initialize PROJECT_STATE.md and .state/checkpoint.json", "status": "in_progress"}
                ]
            },
            {
                "id": "M2",
                "title": "Analytical Database Schema & Storage Engine",
                "status": "pending",
                "tasks": [
                    {"id": "T2.1", "name": "Define SQLAlchemy models for properties, price_history, alerts", "status": "pending"},
                    {"id": "T2.2", "name": "Implement SQLite analytical database manager with DuckDB analytics bridge", "status": "pending"},
                    {"id": "T2.3", "name": "Create database migration and seed utilities", "status": "pending"}
                ]
            },
            {
                "id": "M3",
                "title": "Ingestion Pipeline & Deduplication Engine",
                "status": "pending",
                "tasks": [
                    {"id": "T3.1", "name": "Build HomeHarvest MLS/Realtor scraper with rate-limiting & jitter", "status": "pending"},
                    {"id": "T3.2", "name": "Build mock/synthetic fallback data generator for Duluth, Suwanee, Norcross, Peachtree Corners", "status": "pending"},
                    {"id": "T3.3", "name": "Implement deduplication, price delta detection, and normalization", "status": "pending"}
                ]
            },
            {
                "id": "M4",
                "title": "FastAPI Backend & REST Services",
                "status": "pending",
                "tasks": [
                    {"id": "T4.1", "name": "Build FastAPI app with endpoints for listings, metrics, and price history", "status": "pending"},
                    {"id": "T4.2", "name": "Implement alert rules engine and notification triggers", "status": "pending"},
                    {"id": "T4.3", "name": "Implement manual and scheduled ingestion trigger endpoints", "status": "pending"}
                ]
            },
            {
                "id": "M5",
                "title": "Streamlit Interactive Analytics Dashboard",
                "status": "pending",
                "tasks": [
                    {"id": "T5.1", "name": "Create executive KPI cards: median price, $/sqft, DOM, inventory", "status": "pending"},
                    {"id": "T5.2", "name": "Interactive scatter plots, distribution histograms, and price drop tracker", "status": "pending"},
                    {"id": "T5.3", "name": "Interactive geospatial submarket map with price-per-sqft coloring", "status": "pending"},
                    {"id": "T5.4", "name": "Live deal alerts & ingestion control panel", "status": "pending"}
                ]
            },
            {
                "id": "M6",
                "title": "Testing, Validation & Documentation",
                "status": "pending",
                "tasks": [
                    {"id": "T6.1", "name": "Write automated test suite for database, ingestion, and API", "status": "pending"},
                    {"id": "T6.2", "name": "Validate dashboard on live Streamlit server", "status": "pending"},
                    {"id": "T6.3", "name": "Finalize README.md and operational user guide", "status": "pending"}
                ]
            }
        ],
        "active_blockers": [],
        "target_submarkets": [
            {"city": "Duluth", "zip_codes": ["30096", "30097"], "county": "Gwinnett"},
            {"city": "Suwanee", "zip_codes": ["30024"], "county": "Gwinnett"},
            {"city": "Norcross", "zip_codes": ["30071", "30092", "30093"], "county": "Gwinnett"},
            {"city": "Peachtree Corners", "zip_codes": ["30092"], "county": "Gwinnett"},
            {"city": "Johns Creek", "zip_codes": ["30005", "30022"], "county": "Fulton"},
            {"city": "Alpharetta", "zip_codes": ["30004", "30009"], "county": "Fulton"},
            {"city": "Cumming", "zip_codes": ["30040", "30041"], "county": "Forsyth"}
        ]
    }


def load_checkpoint():
    ensure_state_dir()
    if not CHECKPOINT_FILE.exists():
        data = get_default_checkpoint()
        save_checkpoint(data)
        return data
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(data):
    ensure_state_dir()
    data["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def sync_project_state_md(checkpoint):
    """Regenerate PROJECT_STATE.md from checkpoint.json."""
    md = []
    md.append(f"# {checkpoint['project_name']} - Project State & Tracking")
    md.append("")
    md.append(f"**Current Phase:** {checkpoint['current_phase']}")
    md.append(f"**Last Updated (UTC):** {checkpoint['last_updated']}")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Target Submarkets (Gwinnett & North Fulton)")
    md.append("")
    md.append("| City | ZIP Codes | County |")
    md.append("|---|---|---|")
    for sm in checkpoint.get("target_submarkets", []):
        md.append(f"| {sm['city']} | {', '.join(sm['zip_codes'])} | {sm['county']} |")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Milestones & Task Progress")
    md.append("")

    for m in checkpoint.get("milestones", []):
        status_icon = "🟢 Completed" if m["status"] == "completed" else ("🟡 In Progress" if m["status"] == "in_progress" else "⚪ Pending")
        md.append(f"### [{m['id']}] {m['title']} - {status_icon}")
        md.append("")
        for t in m.get("tasks", []):
            box = "[x]" if t["status"] == "completed" else ("[~]" if t["status"] == "in_progress" else "[ ]")
            md.append(f"- {box} **{t['id']}**: {t['name']} (`{t['status']}`)")
        md.append("")

    md.append("---")
    md.append("")
    md.append("## Active Blockers & Risks")
    blockers = checkpoint.get("active_blockers", [])
    if blockers:
        for b in blockers:
            md.append(f"- ⚠️ {b}")
    else:
        md.append("- None reported. Ingestion, local database, and analytical pipelines operating normally.")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Quick Audit & Inspection Commands")
    md.append("```bash")
    md.append("# Check status")
    md.append("python scripts/checkpoint.py status")
    md.append("")
    md.append("# Start FastAPI Backend")
    md.append("uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --reload")
    md.append("")
    md.append("# Start Streamlit Analytics Dashboard")
    md.append("streamlit run app.py --server.port 8501")
    md.append("```")

    with open(PROJECT_STATE_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")


def update_task_status(task_id: str, new_status: str):
    checkpoint = load_checkpoint()
    found = False
    for m in checkpoint.get("milestones", []):
        for t in m.get("tasks", []):
            if t["id"].lower() == task_id.lower():
                t["status"] = new_status
                found = True
                break
        # update milestone status
        statuses = [t["status"] for t in m.get("tasks", [])]
        if all(s == "completed" for s in statuses):
            m["status"] = "completed"
        elif any(s in ("completed", "in_progress") for s in statuses):
            m["status"] = "in_progress"
        else:
            m["status"] = "pending"

    if found:
        save_checkpoint(checkpoint)
        sync_project_state_md(checkpoint)
        log_history("UPDATE_TASK", f"Task {task_id} set to {new_status}")
        print(f"✅ Updated task {task_id} -> {new_status}")
    else:
        print(f"❌ Task {task_id} not found in checkpoint.")


def set_phase(phase_name: str):
    checkpoint = load_checkpoint()
    checkpoint["current_phase"] = phase_name
    save_checkpoint(checkpoint)
    sync_project_state_md(checkpoint)
    log_history("SET_PHASE", phase_name)
    print(f"✅ Current phase set to: {phase_name}")


def show_status():
    checkpoint = load_checkpoint()
    print("=" * 60)
    print(f"📌 {checkpoint['project_name']} (v{checkpoint['version']})")
    print(f"Phase: {checkpoint['current_phase']}")
    print(f"Last updated: {checkpoint['last_updated']}")
    print("=" * 60)
    for m in checkpoint.get("milestones", []):
        icon = "✅" if m["status"] == "completed" else ("🔄" if m["status"] == "in_progress" else "⏳")
        print(f"\n{icon} {m['id']}: {m['title']} [{m['status'].upper()}]")
        for t in m.get("tasks", []):
            t_icon = "  ✔" if t["status"] == "completed" else ("  ➤" if t["status"] == "in_progress" else "  •")
            print(f"{t_icon} {t['id']}: {t['name']} ({t['status']})")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_status()
    else:
        cmd = sys.argv[1].lower()
        if cmd == "status":
            show_status()
        elif cmd == "sync":
            chk = load_checkpoint()
            sync_project_state_md(chk)
            log_history("SYNC_MD", "PROJECT_STATE.md synchronized with checkpoint.json")
            print("✅ Synchronized PROJECT_STATE.md")
        elif cmd == "update" and len(sys.argv) >= 4:
            task_id = sys.argv[2]
            status = sys.argv[3]
            update_task_status(task_id, status)
        elif cmd == "phase" and len(sys.argv) >= 3:
            phase = " ".join(sys.argv[2:])
            set_phase(phase)
        else:
            print("Usage: checkpoint.py [status|sync|update <task_id> <status>|phase <name>]")
