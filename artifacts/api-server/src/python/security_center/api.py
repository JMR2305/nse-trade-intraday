"""
api.py — Phase 8.6
CLI command functions for the Security & Compliance Centre.

READ-ONLY. ADVISORY-ONLY.
All commands are invoked via main.py and return JSON to stdout.
"""
from security_center.shared_services import (
    get_summary,
    get_auth,
    get_sessions,
    get_secrets,
    get_config,
    get_api_security,
    get_dependencies,
    get_audit_log,
    get_compliance,
    get_alerts,
    get_security_snapshot,
    export_json,
    export_csv,
)

def cmd_summary()      -> dict: return get_summary()
def cmd_auth()         -> dict: return get_auth()
def cmd_sessions()     -> dict: return get_sessions()
def cmd_secrets()      -> dict: return get_secrets()
def cmd_config()       -> dict: return get_config()
def cmd_api()          -> dict: return get_api_security()
def cmd_dependencies() -> dict: return get_dependencies()
def cmd_audit()        -> dict: return get_audit_log()
def cmd_compliance()   -> dict: return get_compliance()
def cmd_alerts()       -> dict: return get_alerts()
def cmd_snapshot()     -> dict: return get_security_snapshot()
def cmd_export_json()  -> dict: return export_json()
def cmd_export_csv()   -> dict: return export_csv()
