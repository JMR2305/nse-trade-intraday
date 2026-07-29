"""
ai_performance/prediction_analysis.py — Binary classification metrics.

Classification rule:
  Positive class = "AI predicts this trade will win"
    → High confidence (>= 60%)
  Negative class = "AI is uncertain"
    → Low confidence (< 60%)
  Actual positive = trade was a winner (pnl > 0)
  Actual negative = trade was a loser (pnl <= 0)

  TP = high confidence + winner
  FP = high confidence + loser
  TN = low confidence + loser
  FN = low confidence + winner

Metrics:
  Precision, Recall (TPR), Accuracy, FPR, FNR, TNR, F1, MCC, Balanced Accuracy

READ-ONLY. PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import math
from typing import List

from .ai_models import AISignalRecord, PredictionMetrics


def compute_prediction_metrics(signals: List[AISignalRecord]) -> PredictionMetrics:
    m = PredictionMetrics()

    if not signals:
        return m

    m.tp = sum(1 for s in signals if s.is_tp)
    m.fp = sum(1 for s in signals if s.is_fp)
    m.tn = sum(1 for s in signals if s.is_tn)
    m.fn = sum(1 for s in signals if s.is_fn)

    tp, fp, tn, fn = m.tp, m.fp, m.tn, m.fn
    total = tp + fp + tn + fn

    # Precision = TP / (TP + FP)
    m.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0

    # Recall / True Positive Rate = TP / (TP + FN)
    m.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    m.true_positive_rate = m.recall

    # True Negative Rate (Specificity) = TN / (TN + FP)
    m.true_negative_rate = tn / (tn + fp) if (tn + fp) > 0 else 0.0

    # False Positive Rate = FP / (FP + TN)
    m.false_positive_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    # False Negative Rate = FN / (FN + TP)
    m.false_negative_rate = fn / (fn + tp) if (fn + tp) > 0 else 0.0

    # Accuracy = (TP + TN) / total
    m.accuracy = (tp + tn) / total if total > 0 else 0.0

    # F1 = 2 * precision * recall / (precision + recall)
    if (m.precision + m.recall) > 0:
        m.f1_score = 2 * m.precision * m.recall / (m.precision + m.recall)
    else:
        m.f1_score = 0.0

    # MCC = (TP*TN - FP*FN) / sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN))
    denom_sq = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    if denom_sq > 0:
        m.mcc = (tp * tn - fp * fn) / math.sqrt(denom_sq)
    else:
        m.mcc = 0.0

    # Balanced Accuracy = (TPR + TNR) / 2
    m.balanced_accuracy = (m.true_positive_rate + m.true_negative_rate) / 2

    # Round all
    m.precision           = round(m.precision, 4)
    m.recall              = round(m.recall, 4)
    m.accuracy            = round(m.accuracy, 4)
    m.false_positive_rate = round(m.false_positive_rate, 4)
    m.false_negative_rate = round(m.false_negative_rate, 4)
    m.true_positive_rate  = round(m.true_positive_rate, 4)
    m.true_negative_rate  = round(m.true_negative_rate, 4)
    m.f1_score            = round(m.f1_score, 4)
    m.mcc                 = round(m.mcc, 4)
    m.balanced_accuracy   = round(m.balanced_accuracy, 4)

    return m
