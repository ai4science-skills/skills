"""Exact calibration and discrimination metrics on caller-supplied probabilities.

No model weights are loaded here. No hardware claims. Pure math, deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def _validate(probs: list[float], labels: list[int]) -> None:
    if len(probs) != len(labels):
        raise ValueError("probabilities and labels must have equal length")
    if not probs:
        raise ValueError("empty input is REVIEW, not a score")
    for p in probs:
        if not (0.0 <= p <= 1.0) or math.isnan(p):
            raise ValueError(f"probability out of [0,1]: {p!r}")
    for y in labels:
        if y not in (0, 1):
            raise ValueError(f"label must be 0 or 1: {y!r}")


def brier_score(probs: list[float], labels: list[int]) -> float:
    _validate(probs, labels)
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def log_loss(probs: list[float], labels: list[int], eps: float = 1e-15) -> float:
    _validate(probs, labels)
    total = 0.0
    for p, y in zip(probs, labels):
        p = min(max(p, eps), 1.0 - eps)
        total += y * math.log(p) + (1 - y) * math.log(1 - p)
    return -total / len(probs)


@dataclass(frozen=True)
class Bin:
    lo: float
    hi: float
    count: int
    mean_confidence: float
    accuracy: float


def reliability_bins(probs: list[float], labels: list[int], n_bins: int = 10) -> list[Bin]:
    _validate(probs, labels)
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probs, labels):
        i = min(int(p * n_bins), n_bins - 1)
        buckets[i].append((p, y))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        mc = sum(p for p, _ in b) / len(b)
        ac = sum(y for _, y in b) / len(b)
        out.append(Bin(lo=i / n_bins, hi=(i + 1) / n_bins, count=len(b),
                       mean_confidence=mc, accuracy=ac))
    return out


def expected_calibration_error(probs: list[float], labels: list[int], n_bins: int = 10) -> float:
    bins = reliability_bins(probs, labels, n_bins)
    n = len(probs)
    return sum((b.count / n) * abs(b.accuracy - b.mean_confidence) for b in bins)


def maximum_calibration_error(probs: list[float], labels: list[int], n_bins: int = 10) -> float:
    bins = reliability_bins(probs, labels, n_bins)
    return max((abs(b.accuracy - b.mean_confidence) for b in bins), default=0.0)


def auroc(scores: list[float], labels: list[int]) -> float:
    """Rank-based AUROC (Mann-Whitney) with tie-averaged ranks. Exact, no dependencies."""
    _validate(scores, labels)
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    pos = [r for r, y in zip(ranks, labels) if y == 1]
    n_pos, n_neg = len(pos), len(labels) - len(pos)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUROC undefined: need both classes present")
    return (sum(pos) - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
