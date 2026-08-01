"""
api.py — Phase 8.7 Performance Centre
CLI command dispatch functions, one-to-one with shared_services.

READ-ONLY. ADVISORY-ONLY.
"""
from .shared_services import (
    get_performance_summary,
    get_api_performance,
    get_database_performance,
    get_cache_performance,
    get_scheduler_performance,
    get_resource_performance,
    get_frontend_performance,
    get_scalability_estimate,
    get_benchmark,
    get_recommendations,
    get_performance_snapshot,
    get_export_json,
    get_export_csv,
)


def cmd_summary()         -> dict: return get_performance_summary()
def cmd_api()             -> dict: return get_api_performance()
def cmd_database()        -> dict: return get_database_performance()
def cmd_cache()           -> dict: return get_cache_performance()
def cmd_scheduler()       -> dict: return get_scheduler_performance()
def cmd_resources()       -> dict: return get_resource_performance()
def cmd_frontend()        -> dict: return get_frontend_performance()
def cmd_scalability()     -> dict: return get_scalability_estimate()
def cmd_benchmark()       -> dict: return get_benchmark()
def cmd_recommendations() -> dict: return get_recommendations()
def cmd_snapshot()        -> dict: return get_performance_snapshot()
def cmd_export_json()     -> dict: return get_export_json()
def cmd_export_csv()      -> dict: return get_export_csv()
