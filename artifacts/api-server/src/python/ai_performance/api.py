"""
ai_performance/api.py — HTTP API façade for Phase 5D.4.

6 read-only endpoints:
  GET /api/ai/summary
  GET /api/ai/confidence
  GET /api/ai/calibration
  GET /api/ai/predictions
  GET /api/ai/recommendations
  GET /api/ai/learning

Phase 5D.5 MUST import from shared_services, not this module.
This module is the HTTP API layer only.

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

from .ai_models import is_enabled, disabled_response


def get_summary() -> dict:
    """GET /api/ai/summary"""
    if not is_enabled():
        return disabled_response()
    from .shared_services import get_ai_summary
    return get_ai_summary()


def get_confidence() -> dict:
    """GET /api/ai/confidence"""
    if not is_enabled():
        return disabled_response()
    from .shared_services import get_confidence_data
    return get_confidence_data()


def get_calibration() -> dict:
    """GET /api/ai/calibration"""
    if not is_enabled():
        return disabled_response()
    from .shared_services import get_calibration_data
    return get_calibration_data()


def get_predictions() -> dict:
    """GET /api/ai/predictions"""
    if not is_enabled():
        return disabled_response()
    from .shared_services import get_prediction_data
    return get_prediction_data()


def get_recommendations() -> dict:
    """GET /api/ai/recommendations"""
    if not is_enabled():
        return disabled_response()
    from .shared_services import get_recommendation_data
    return get_recommendation_data()


def get_learning() -> dict:
    """GET /api/ai/learning"""
    if not is_enabled():
        return disabled_response()
    from .shared_services import get_learning_data
    return get_learning_data()
