from __future__ import annotations
import time, json, datetime as dt
from typing import Any, Dict, List, Optional
from .exchange import Exchange, Candle
# Import the global metrics collector. This module initialises a singleton
# instance via init_metrics() during application startup. When None, metrics
# collection is disabled and no recording occurs. We import it here at
# module level to avoid circular imports and allow safe access during
# order submission. See bingx_bot/bot/metrics.py for details.
from .metrics import metrics as global_metrics

class Trader:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        # Determine the exchange ID and secondary exchange ID from the config.
        # The Exchange constructor reads these from environment variables; we
        # set them here so that failover works transparently. Primary and
        # secondary identifiers can also be passed via the config.
        import os as _os
        # Overwrite environment variables for this process so that the
        # Exchange instance will pick up the correct IDs.
        if cfg.get('exchange_id'):
            _os.environ['EXCHANGE_ID'] = str(cfg.get('exchange_id'))
        if cfg.get('secondary_exchange_id'):
            _os.environ['SECONDARY_EXCHANGE_ID'] = str(cfg.get('secondary_exchange_id'))
        self.ex = Exchange(cfg.get('symbol','BTC/USDT:USDT'), dry_run=bool(cfg.get('dry_run', True)))
        self.last_trade_ts: Optional[int] = None

        # Trading profile determines risk parameters when explicit values
        # (max_positions, daily_loss_pct) are not provided. Profiles are
        # configured via cfg['profile'] or the TRADER_PROFILE environment.
        self.profile = (cfg.get('profile')
                        or _os.getenv('TRADER_PROFILE')
                        or 'paper').lower()
        # Load profile defaults
        profile_defaults = {
            'paper':      {'max_positions': 0, 'daily_loss_pct': 0.0},
            'shadow':     {'max_positions': 0, 'daily_loss_pct': 0.0},
            'live-small': {'max_positions': 1, 'daily_loss_pct': 5.0},
            'live-normal':{'max_positions': 3, 'daily_loss_pct': 3.0},
        }
        defaults = profile_defaults.get(self.profile, {'max_positions': 1, 'daily_loss_pct': 0.0})
        # Maximum number of allowed entries per day. A circuit breaker to limit
        # excessive trading or runaway loops.
        try:
            self.max_positions = int(cfg.get('max_positions')) if cfg.get('max_positions') is not None else int(defaults['max_positions'])
        except Exception:
            self.max_positions = int(defaults['max_positions'])
        # Count of trades executed today and the date they were recorded. This
        # resets when the calendar day rolls over. Each time an order is
        # successfully placed via _send_order(), trades_today is incremented.
        self.trades_today: int = 0
        import datetime as _dt
        self.trades_date: _dt.date = _dt.date.today()
        # Daily loss limit percentage; if specified the bot could implement a
        # circuit breaker to stop trading after exceeding this loss.
        try:
            self.daily_loss_pct = float(cfg.get('daily_loss_pct')) if cfg.get('daily_loss_pct') is not None else float(defaults['daily_loss_pct'])
        except Exception:
            self.daily_loss_pct = float(defaults['daily_loss_pct'])

    def _now_ok(self) -> bool:
        ss = (self.cfg.get('session_start') or '').strip()
        se = (self.cfg.get('session_end') or '').strip()
        if not ss and not se:
            return True
        now = dt.datetime.now().time()
        def parse(hhmm:str):
            try:
                h,m = hhmm.split(':'); return dt.time(int(h), int(m))
            except Exception:
                return None
        ps, pe = parse(ss), parse(se)
        if ps and pe:
            if ps <= pe:
                return ps <= now <= pe
            else:
                return not (pe < now < ps)
        return True

    def _cooldown_ok(self) -> bool:
        cd = int(self.cfg.get('cooldown_sec') or 0)
        if not cd or not self.last_trade_ts:
            return True
        return (time.time() - self.last_trade_ts) >= cd

    def _position_size_usd(self, balance_usdt: Optional[float]) -> float:
        mode = (self.cfg.get('ps_mode') or 'fixed').lower()
        val = float(self.cfg.get('ps_value') or self.cfg.get('usd_per_trade') or 50)
        if mode == 'percent' and balance_usdt:
            return max(0.0, float(balance_usdt) * float(val) / 100.0)
        return max(0.0, float(val))

    def _daily_risk_ok(self) -> bool:
        # Placeholder for daily risk management. A full implementation would
        # compare realised PnL against the configured daily_loss_pct and halt
        # trading when exceeded. Here we simply always allow trading.
        return True

    def _position_limit_ok(self) -> bool:
        """Return True if another position can be opened today based on
        max_positions and trades_today. Resets the counter on a new day."""
        import datetime as _dt
        today = _dt.date.today()
        if today != self.trades_date:
            self.trades_date = today
            self.trades_today = 0
        return self.trades_today < self.max_positions

    def _send_order(self, symbol: str, side: str, order_type: str, amount: float,
                    price: Optional[float], params: Dict[str, Any], retries: int = 3,
                    delay: float = 5.0) -> Dict[str, Any]:
        """Send an order with a simple retry/backoff strategy.

        This helper wraps `Exchange.create_order` with timing and error
        collection. On each attempt it measures the latency of the order
        submission and records it via the global metrics collector. If an
        exception is thrown or the API returns a non-ok result, an error
        counter is incremented. The call retries up to `retries` times
        waiting `delay` seconds between attempts. The most recent response
        (successful or failed) is returned."""
        last_res: Dict[str, Any] = {}
        # Enforce at least one attempt
        attempts = max(1, retries)
        for attempt in range(attempts):
            start_ts = time.time()
            try:
                # Attempt to place the order via the exchange
                res = self.ex.create_order(
                    symbol=symbol,
                    side=side,
                    type=order_type,
                    amount=amount,
                    price=price,
                    params=params,
                )
                # If the response indicates failure (ok=False), treat as error
                if not res or res.get('ok', True) is False:
                    # Record error in metrics
                    try:
                        if global_metrics is not None:
                            global_metrics.record_error()
                    except Exception:
                        pass
                    last_res = res
                    # Back off before retrying
                    if attempt < attempts - 1:
                        time.sleep(delay)
                    continue
                # Successful response: update trades counter and return
                try:
                    self.trades_today += 1
                except Exception:
                    pass
                return res
            except Exception:
                # Capture exceptions from create_order, increment error count
                try:
                    if global_metrics is not None:
                        global_metrics.record_error()
                except Exception:
                    pass
                last_res = {"ok": False, "error": "order_exception"}
                # On any exception, sleep before retrying unless this was the last attempt
                if attempt < attempts - 1:
                    time.sleep(delay)
            finally:
                # In case of exception or success, ensure latency is recorded
                # If an exception was thrown before calculating latency, compute it now
                try:
                    if 'latency_ms' not in locals():
                        latency_ms = (time.time() - start_ts) * 1000.0
                    if global_metrics is not None:
                        global_metrics.record_order_latency(latency_ms)
                except Exception:
                    pass
        return last_res

    def _filters_ok(self, candles: List[Candle]) -> bool:
        mv = self.cfg.get('min_volume')
        if mv is not None and candles:
            v = candles[-1].volume
            if v is not None and v < float(mv):
                return False
        max_atr = self.cfg.get('max_atr_pct')
        if max_atr is not None and len(candles) >= 14:
            tr = []
            for i in range(1,15):
                c0, c1 = candles[-i], candles[-i-1]
                tr.append(max(c0.high-c0.low, abs(c0.high-c1.close), abs(c0.low-c1.close)))
            atr = sum(tr)/len(tr)
            if candles[-1].close>0:
                if (atr / candles[-1].close) * 100.0 > float(max_atr):
                    return False
        return True

    def _entry_signal(self, candles: List[Candle]) -> Optional[str]:
        if len(candles) < 25:
            return None
        closes = [c.close for c in candles[-25:]]
        sma20 = sum(closes[-20:]) / 20.0
        if closes[-2] < sma20 and closes[-1] > sma20:
            return 'long'
        if closes[-2] > sma20 and closes[-1] < sma20:
            return 'short'
        return None

    def _limit_price(self, side: str, mark: float) -> float:
        sp = float(self.cfg.get('slippage_pct') or 0.2) / 100.0
        if side == 'long':
            return mark * (1 - sp)
        else:
            return mark * (1 + sp)

    def _emit_status(self, price, position, balance) -> None:
        try:
            print("STATUS " + json.dumps({"price": price, "position": position, "balance": balance}), flush=True)
        except Exception:
            pass

    def run(self) -> None:
        sym = self.cfg.get('symbol','BTC/USDT:USDT')
        tf = self.cfg.get('timeframe','15m')
        lookback = int(self.cfg.get('lookback') or 300)
        loop = bool(self.cfg.get('loop', True))

        while True:
            try:
                if not self._now_ok() or not self._cooldown_ok() or not self._daily_risk_ok():
                    time.sleep(float(self.cfg.get('sleep') or 15));
                    continue

                price = self.ex.get_last_price() or 0.0
                candles = self.ex.fetch_ohlcv(tf, limit=lookback) or []
                pos = self.ex.get_open_position()
                bal = self.ex.get_balance()
                self._emit_status(price, pos, bal)

                if not candles:
                    time.sleep(float(self.cfg.get('sleep') or 15));
                    continue
                if not self._filters_ok(candles):
                    time.sleep(float(self.cfg.get('sleep') or 15));
                    continue

                sig = self._entry_signal(candles)
                if sig and price>0:
                    # Enforce per-day position limit before attempting to place a new order
                    if not self._position_limit_ok():
                        # Skip opening additional positions until the next day
                        time.sleep(float(self.cfg.get('sleep') or 15))
                        continue
                    size_usd = self._position_size_usd(bal.get('total') if bal else None)
                    if size_usd <= 0:
                        time.sleep(float(self.cfg.get('sleep') or 15))
                        continue
                    qty = size_usd / price
                    order_type = (self.cfg.get('order_type') or 'market').lower()
                    params = {
                        'reduceOnly': bool(self.cfg.get('reduce_only')),
                        'postOnly': bool(self.cfg.get('post_only')),
                        'timeInForce': self.cfg.get('tif', 'GTC')
                    }
                    px = None
                    if order_type != 'market':
                        px = self._limit_price('long' if sig == 'long' else 'short', price)
                    # Place the order via the retry-enabled helper
                    res = self._send_order(
                        symbol=sym,
                        side=('buy' if sig == 'long' else 'sell'),
                        order_type=order_type,
                        amount=qty,
                        price=px,
                        params=params
                    )
                    print("LOG " + json.dumps({"event": "order", "result": res}), flush=True)
                    self.last_trade_ts = time.time()

            except Exception as e:
                print('ERR', e, flush=True)

            if not loop:
                break
            time.sleep(float(self.cfg.get('sleep') or 15))
