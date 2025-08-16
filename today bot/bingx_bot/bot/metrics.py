"""Metrics collection utilities for the trading bot.

This module defines a MetricsCollector class that accumulates various runtime
metrics such as order latency, error rate, WebSocket reconnect count and
simple drift statistics. An instance of this class is created by the
application at startup (via init_metrics) and shared across modules so
components can record and query metrics without coupling.

The collector stores metrics in memory and exposes a summary dictionary via
get_metrics(). Drawdown is computed based on an equity history supplied by
the caller.

Note: This is a lightweight implementation suitable for educational and
development purposes. In a production environment you may want to export
metrics to a time series database (e.g., Prometheus) or integrate with a
monitoring system.
"""
from __future__ import annotations

import time
import sqlite3
from typing import Any, Dict, List, Optional


class MetricsCollector:
    """Collects and summarises runtime metrics for the trading bot."""

    def __init__(self, db_path: str) -> None:
        # Path to the SQLite trade history. Currently unused but reserved for
        # future metrics that require reading the DB (e.g. realised PnL).
        self.db_path: str = str(db_path)
        # Latencies of order submissions in milliseconds.
        self.order_latencies: List[float] = []
        # Count of orders attempted.
        self.order_count: int = 0
        # Count of order errors encountered.
        self.error_count: int = 0
        # Count of WebSocket reconnect events.
        self.ws_reconnects: int = 0
        # Price drift measurements between WS and REST (arbitrary units).
        self.price_drifts: List[float] = []
        # Equity history used to compute drawdown.
        self.equity_history: List[float] = []

    def record_order_latency(self, latency_ms: float) -> None:
        """Record the latency (in milliseconds) of an order submission."""
        try:
            self.order_latencies.append(float(latency_ms))
            self.order_count += 1
        except Exception:
            # Ignore unexpected values
            pass

    def record_error(self) -> None:
        """Increment the global error count."""
        self.error_count += 1

    def increment_ws_reconnect(self) -> None:
        """Increment the WebSocket reconnect counter."""
        self.ws_reconnects += 1

    def record_price_drift(self, drift: float) -> None:
        """Record a drift value between WS and REST prices."""
        try:
            self.price_drifts.append(float(drift))
        except Exception:
            pass

    def record_equity(self, equity: float) -> None:
        """Append an equity value to the history for drawdown calculations."""
        try:
            self.equity_history.append(float(equity))
        except Exception:
            pass

    def compute_drawdown(self) -> Optional[float]:
        """Compute the maximum drawdown based on the recorded equity history.

        Returns None if not enough data has been recorded.
        """
        if not self.equity_history:
            return None
        peak: float = self.equity_history[0]
        max_dd: float = 0.0
        for eq in self.equity_history:
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
        return max_dd

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of current metrics as a dictionary.

        This method computes simple summaries such as average latency,
        error rate and average price drift on demand. Drawdown is computed
        from the stored equity history.
        """
        avg_latency: Optional[float] = None
        if self.order_latencies:
            try:
                avg_latency = sum(self.order_latencies) / len(self.order_latencies)
            except Exception:
                avg_latency = None
        error_rate: Optional[float] = None
        if self.order_count:
            error_rate = self.error_count / self.order_count
        drift_avg: Optional[float] = None
        if self.price_drifts:
            try:
                drift_avg = sum(self.price_drifts) / len(self.price_drifts)
            except Exception:
                drift_avg = None
        return {
            "order_count": self.order_count,
            "order_latency_avg_ms": avg_latency,
            "order_error_rate": error_rate,
            "ws_reconnects": self.ws_reconnects,
            "price_drift_avg": drift_avg,
            "equity_drawdown": self.compute_drawdown(),
        }


# Global metrics collector instance. This is initialised via init_metrics()
metrics: Optional[MetricsCollector] = None


def init_metrics(db_path: str) -> MetricsCollector:
    """Initialise the global metrics collector with the given DB path.

    Subsequent calls return the existing instance. Components should call
    init_metrics during application startup to ensure the collector is
    available.
    """
    global metrics
    if metrics is None:
        metrics = MetricsCollector(db_path)
    return metrics