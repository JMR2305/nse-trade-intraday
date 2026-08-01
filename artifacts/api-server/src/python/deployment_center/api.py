"""
api.py — Phase 8.8
CLI command functions for the Deployment & Disaster Recovery Centre.

READ-ONLY. ADVISORY-ONLY.
All commands are invoked via main.py and return JSON to stdout.
"""
from deployment_center.shared_services import (
    get_summary,
    get_readiness,
    get_config,
    get_backups,
    get_restore,
    get_rollback,
    get_infrastructure,
    get_continuity,
    get_recommendations,
    get_deployment_snapshot,
    export_json,
    export_csv,
)

def cmd_summary()         -> dict: return get_summary()
def cmd_readiness()       -> dict: return get_readiness()
def cmd_config()          -> dict: return get_config()
def cmd_backups()         -> dict: return get_backups()
def cmd_restore()         -> dict: return get_restore()
def cmd_rollback()        -> dict: return get_rollback()
def cmd_infrastructure()  -> dict: return get_infrastructure()
def cmd_continuity()      -> dict: return get_continuity()
def cmd_recommendations() -> dict: return get_recommendations()
def cmd_snapshot()        -> dict: return get_deployment_snapshot()
def cmd_export_json()     -> dict: return export_json()
def cmd_export_csv()      -> dict: return export_csv()
