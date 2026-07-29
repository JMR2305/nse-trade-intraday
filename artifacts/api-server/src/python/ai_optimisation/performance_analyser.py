"""
performance_analyser.py — Phase 6.3
Prediction quality metrics from paper trade records.

Metrics: accuracy, precision, recall, F1, FPR, FNR,
         avg confidence, confidence error, calibration score,
         prediction stability, recommendation consistency.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
import math
from typing import List


def _avg(vals: list) -> float:
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else 0.0


def _std(vals: list) -> float:
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return 0.0
    mean = sum(v) / len(v)
    return math.sqrt(sum((x - mean) ** 2 for x in v) / len(v))


def analyse_prediction_quality(records: list) -> dict:
    """
    Compute prediction-quality metrics over all closed trade records.

    A trade is classified as:
        TP  — ai_recommendation == "BUY" and pnl > 0
        FP  — ai_recommendation == "BUY" and pnl <= 0
        TN  — ai_recommendation == "SELL" and pnl <= 0  (avoided a loss)
        FN  — ai_recommendation == "SELL" and pnl > 0   (missed a gain)
    """
    if not records:
        return _empty_result()

    tp = fp = tn = fn = 0
    confidences: List[float] = []
    returns: List[float] = []

    for r in records:
        conf = r.ai_confidence if r.ai_confidence is not None else 0.0
        confidences.append(conf)
        if r.pnl_pct is not None:
            returns.append(r.pnl_pct)

        rec = (r.ai_recommendation or "").upper()
        win = r.pnl > 0 if r.pnl is not None else False

        if rec == "BUY":
            if win:
                tp += 1
            else:
                fp += 1
        else:
            if not win:
                tn += 1
            else:
                fn += 1

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0

    avg_conf = _avg(confidences)
    conf_error = abs(avg_conf - accuracy)

    # Calibration score: 1 - ECE (mean |conf - accuracy| by bucket)
    ece = _compute_ece(records)
    calibration_score = max(0.0, 1.0 - ece)

    # Prediction stability: 1 - std(rolling 10-trade accuracy windows)
    stab = _rolling_accuracy_stability(records)

    # Recommendation consistency: proportion of same-condition trades
    # that share the same recommendation
    consistency = _recommendation_consistency(records)

    return {
        "total_signals": total,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
        "avg_confidence": round(avg_conf, 4),
        "confidence_error": round(conf_error, 4),
        "calibration_score": round(calibration_score, 4),
        "ece": round(ece, 4),
        "prediction_stability": round(stab, 4),
        "recommendation_consistency": round(consistency, 4),
    }


def _compute_ece(records: list, n_bins: int = 5) -> float:
    """Expected Calibration Error over n confidence bins."""
    if not records:
        return 0.0
    bin_size = 1.0 / n_bins
    bins: list = [[] for _ in range(n_bins)]
    for r in records:
        conf = r.ai_confidence if r.ai_confidence is not None else 0.0
        win = (r.pnl or 0) > 0
        idx = min(int(conf / bin_size), n_bins - 1)
        bins[idx].append((conf, win))
    ece = 0.0
    total = len(records)
    for b in bins:
        if not b:
            continue
        avg_c = sum(x[0] for x in b) / len(b)
        avg_a = sum(1 for x in b if x[1]) / len(b)
        ece += (len(b) / total) * abs(avg_c - avg_a)
    return ece


def _rolling_accuracy_stability(records: list, window: int = 10) -> float:
    if len(records) < window:
        return 0.5
    sorted_recs = sorted(records, key=lambda r: r.timestamp)
    accuracies = []
    for i in range(len(sorted_recs) - window + 1):
        chunk = sorted_recs[i:i + window]
        acc = sum(1 for r in chunk if (r.pnl or 0) > 0) / window
        accuracies.append(acc)
    std = _std(accuracies)
    return round(max(0.0, 1.0 - std * 3.0), 4)


def _recommendation_consistency(records: list) -> float:
    """
    Group by (strategy, market_regime) and measure how often the same
    recommendation appears. High = consistent.
    """
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for r in records:
        key = (r.strategy, r.market_regime)
        groups[key].append((r.ai_recommendation or "").upper())

    if not groups:
        return 0.5
    consistencies = []
    for recs in groups.values():
        if len(recs) < 2:
            continue
        from collections import Counter
        most_common_count = Counter(recs).most_common(1)[0][1]
        consistencies.append(most_common_count / len(recs))
    return _avg(consistencies) if consistencies else 0.5


def _empty_result() -> dict:
    return {
        "total_signals": 0,
        "tp": 0, "fp": 0, "tn": 0, "fn": 0,
        "accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1_score": 0.0,
        "false_positive_rate": 0.0, "false_negative_rate": 0.0,
        "avg_confidence": 0.0, "confidence_error": 0.0,
        "calibration_score": 0.0, "ece": 0.0,
        "prediction_stability": 0.0, "recommendation_consistency": 0.0,
    }
