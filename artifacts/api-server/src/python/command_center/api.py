"""
api.py — Phase 9.1
CLI command functions for the Unified Command Centre.

READ-ONLY. ADVISORY-ONLY.
All commands are invoked via main.py and return JSON to stdout.
"""
from command_center.shared_services import (
    get_summary,
    get_briefing,
    get_alerts,
    get_timeline,
    get_command_center_snapshot,
    export_json,
    export_csv,
)

def cmd_summary()    -> dict: return get_summary()
def cmd_briefing()   -> dict: return get_briefing()
def cmd_alerts()     -> dict: return get_alerts()
def cmd_timeline()   -> dict: return get_timeline()
def cmd_snapshot()   -> dict: return get_command_center_snapshot()
def cmd_export_json()-> dict: return export_json()
def cmd_export_csv() -> dict: return export_csv()
