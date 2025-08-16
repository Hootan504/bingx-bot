"""Tests for the metrics and trader modules.

This module contains a collection of unit tests exercising the metrics
collection functionality and the Trader._send_order method. These tests
ensure that basic metrics (latency and error rate) are recorded correctly
under both successful and failing conditions. Use `pytest` to run the
tests (e.g. `pytest -q`).
"""
from __future__ import annotations

import types
import builtins

import pytest

from bingx_bot.bot.metrics import MetricsCollector, init_metrics
from bingx_bot.bot.trader import Trader


class StubExchange:
    """A minimal stub for the Exchange class used by Trader.

    It records the number of times `create_order` has been called and
    optionally raises exceptions to simulate API failures.
    """

    def __init__(self, success: bool = True, raise_exc: bool = False) -> None:
        self.calls = 0
        self.success = success
        self.raise_exc = raise_exc

    def create_order(self, *args, **kwargs):  # type: ignore[override]
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("create_order failure")
        return {"ok": self.success, "symbol": kwargs.get("symbol"), "side": kwargs.get("side"), "type": kwargs.get("type"), "amount": kwargs.get("amount"), "price": kwargs.get("price"), "params": kwargs.get("params")}


def test_metrics_collector_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure MetricsCollector records latency, errors and equity drawdown."""
    # Reset the global metrics to a fresh collector to avoid interference
    collector = MetricsCollector(db_path=":memory:")
    # Patch the module-level metrics object so computations remain isolated
    import bingx_bot.bot.metrics as metrics_module  # type: ignore
    monkeypatch.setattr(metrics_module, "metrics", collector, raising=False)
    mc = collector
    mc.record_order_latency(100.0)
    mc.record_order_latency(200.0)
    mc.record_error()
    mc.record_equity(100.0)
    mc.record_equity(95.0)
    mc.record_equity(110.0)
    # Compute drawdown: peak=100->dd=5 when equity=95, resets with 110
    dd = mc.compute_drawdown()
    assert dd is not None
    assert abs(dd - 5.0) < 1e-6
    metrics = mc.get_metrics()
    # Average latency should be 150
    assert abs(metrics.get("order_latency_avg_ms", 0) - 150.0) < 1e-3
    # Error rate should be 1/2 = 0.5
    assert abs(metrics.get("order_error_rate", 0) - 0.5) < 1e-3


def test_trader_send_order_success_records_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a successful order records latency but not errors."""
    # Reset the global metrics collector
    # Reset global metrics instance
    import bingx_bot.bot.metrics as metrics_module  # type: ignore
    collector = MetricsCollector(db_path=":memory:")
    monkeypatch.setattr(metrics_module, "metrics", collector, raising=False)
    mc = collector
    # Create a trader with default config and stub exchange returning success
    t = Trader(cfg={})
    stub = StubExchange(success=True)
    # Patch the trader's exchange instance
    t.ex = stub  # type: ignore
    # Place one order
    res = t._send_order(
        symbol="BTC/USDT:USDT",
        side="buy",
        order_type="market",
        amount=1.0,
        price=None,
        params={},
        retries=1,
        delay=0.1,
    )
    assert res.get("ok") is True
    # Ensure one latency measurement has been recorded
    data = mc.get_metrics()
    assert data["order_count"] >= 1
    # Error rate should be 0
    assert data["order_error_rate"] == 0


def test_trader_send_order_failure_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a failed order (exception) increments the error counter."""
    import bingx_bot.bot.metrics as metrics_module  # type: ignore
    collector = MetricsCollector(db_path=":memory:")
    monkeypatch.setattr(metrics_module, "metrics", collector, raising=False)
    mc = collector
    t = Trader(cfg={})
    # Use stub that raises exception
    stub = StubExchange(success=False, raise_exc=True)
    t.ex = stub  # type: ignore
    res = t._send_order(
        symbol="BTC/USDT:USDT",
        side="buy",
        order_type="market",
        amount=1.0,
        price=None,
        params={},
        retries=1,
        delay=0.1,
    )
    # Should return non-ok result due to exception
    assert res.get("ok") is False
    data = mc.get_metrics()
    # Error count should be at least 1
    assert data["order_error_rate"] == 1.0