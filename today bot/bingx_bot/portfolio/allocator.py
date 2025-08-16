"""Allocation strategies for multi-asset portfolios.

This module contains a small set of allocator classes which determine how
capital is distributed across multiple trading symbols. The goal is to
control risk by weighting assets according to volatility or applying
static weights. Correlation-based allocation is left as an exercise for
extension.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple


class BaseAllocator:
    """Abstract base class for portfolio allocators.

    An allocator takes a list of tuples representing assets and returns a
    dictionary mapping symbols to their target weights. Each tuple
    typically contains (symbol, volatility, correlation) but can be
    extended.
    """

    def allocate(self, assets: List[Tuple[str, float, float]]) -> Dict[str, float]:
        raise NotImplementedError


class FixedAllocator(BaseAllocator):
    """Allocator that returns predetermined weights.

    Provide a mapping of symbol -> weight at construction. Missing
    symbols will receive a weight of zero.
    """

    def __init__(self, weights: Dict[str, float]) -> None:
        self.weights = weights or {}

    def allocate(self, assets: List[Tuple[str, float, float]]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        # Normalise weights so that they sum to 1
        total = sum(max(w, 0.0) for w in self.weights.values())
        total = total if total > 0 else 1.0
        for symbol, _, _ in assets:
            w = self.weights.get(symbol, 0.0)
            result[symbol] = max(w, 0.0) / total
        return result


class VolTargetAllocator(BaseAllocator):
    """Allocator that targets equal risk (1/volatility) allocation.

    Weights are proportional to the inverse of volatility squared. If
    volatility is zero or unavailable, the asset receives zero weight. The
    result is normalised so that weights sum to 1.
    """

    def allocate(self, assets: List[Tuple[str, float, float]]) -> Dict[str, float]:
        inv_vars: Dict[str, float] = {}
        for symbol, vol, _corr in assets:
            try:
                if vol and vol > 0:
                    inv_vars[symbol] = 1.0 / (vol * vol)
                else:
                    inv_vars[symbol] = 0.0
            except Exception:
                inv_vars[symbol] = 0.0
        total = sum(inv_vars.values())
        total = total if total > 0 else 1.0
        return {sym: w / total for sym, w in inv_vars.items()}


class CorrelationAllocator(BaseAllocator):
    """Allocator that reduces exposure to highly correlated assets.

    This simple implementation assigns zero weight to any asset whose
    correlation exceeds a user-provided threshold. Remaining assets are
    weighted equally. In practice you would compute correlations
    dynamically from historical price series.
    """

    def __init__(self, corr_threshold: float = 0.9) -> None:
        self.corr_threshold = corr_threshold

    def allocate(self, assets: List[Tuple[str, float, float]]) -> Dict[str, float]:
        selected: List[str] = []
        for symbol, _vol, corr in assets:
            try:
                if abs(corr) < self.corr_threshold:
                    selected.append(symbol)
            except Exception:
                continue
        n = len(selected)
        if n == 0:
            return {symbol: 0.0 for symbol, _, _ in assets}
        w = 1.0 / n
        return {symbol: (w if symbol in selected else 0.0) for symbol, _, _ in assets}