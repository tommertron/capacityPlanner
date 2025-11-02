from __future__ import annotations

import math
from typing import Iterable, List, Sequence


def normalize_curve(seq: Iterable[float]) -> List[float]:
    values = [float(x) for x in seq]
    if not values:
        raise ValueError("curve must contain at least one value")
    if any(v < 0 for v in values):
        raise ValueError("curve values must be non-negative")
    total = sum(values)
    if total <= 0:
        raise ValueError("curve values must sum to a positive number")
    normalized = [v / total for v in values]
    total_normalized = sum(normalized)
    if abs(total_normalized - 1.0) > 1e-6:
        normalized = [v / total_normalized for v in normalized]
    return normalized


def uniform_curve(size: int) -> List[float]:
    if size <= 0:
        raise ValueError("uniform curve size must be positive")
    weight = 1.0 / size
    return [weight] * size


def _cdf_value(weights: Sequence[float], prefix: Sequence[float], x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    scaled = x * len(weights)
    idx = int(math.floor(scaled))
    frac = scaled - idx
    if idx >= len(weights):
        return 1.0
    base = prefix[idx]
    return base + weights[idx] * frac


def _resample_curve(base: Sequence[float], buckets: int) -> List[float]:
    if buckets <= 0:
        raise ValueError("requested bucket count must be positive")
    if len(base) == 0:
        raise ValueError("base curve cannot be empty")
    normalized_base = normalize_curve(base)
    if buckets == len(normalized_base):
        return normalized_base
    if buckets == 1:
        return [1.0]
    prefix = [0.0]
    total = 0.0
    for value in normalized_base:
        total += value
        prefix.append(total)
    buckets_weights: List[float] = []
    for idx in range(buckets):
        lower = idx / buckets
        upper = (idx + 1) / buckets
        share = _cdf_value(normalized_base, prefix, upper) - _cdf_value(normalized_base, prefix, lower)
        buckets_weights.append(share)
    return normalize_curve(buckets_weights)


def resolve_curve(spec: object, buckets: int) -> List[float]:
    if isinstance(spec, str):
        if spec.lower() == "uniform":
            return uniform_curve(buckets)
        raise ValueError(f"unsupported curve keyword '{spec}'")
    if isinstance(spec, Sequence):
        return _resample_curve(list(spec), buckets)
    raise TypeError("curve spec must be a sequence of floats or 'uniform'")
