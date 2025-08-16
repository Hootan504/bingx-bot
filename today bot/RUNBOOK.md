# Runbook for BingX/Binance Trading Bot

This runbook provides operational guidance for common scenarios encountered
when running the trading bot in production. Operators should consult this
document when alerts are triggered or when investigating abnormal behaviour.

## Table of Contents

1. [WebSocket Disconnects](#websocket-disconnects)
2. [High Error Rate](#high-error-rate)
3. [Equity Drawdown Exceeded](#equity-drawdown-exceeded)
4. [Position Mismatch](#position-mismatch)
5. [Overfill or Partial Fill Issues](#overfill-or-partial-fill-issues)
6. [Liquidation Risk](#liquidation-risk)

---

### WebSocket Disconnects

**Symptoms:** The monitoring dashboard reports a high number of WS reconnects or
alerts that the WebSocket has been down for more than 30 seconds.

**Actions:**
1. Check network connectivity from the host machine to the exchange. A simple
   `ping` or `curl` to the exchange API endpoint can validate connectivity.
2. Review recent log entries (`/logs` endpoint) for messages indicating
   authentication failures or rate limiting.
3. If connectivity is unstable, the bot will automatically fall back to REST
   APIs for price data. Monitor the `price_drift_avg` metric to ensure REST
   prices remain reasonable compared to the last known WS price.
4. If the outage persists beyond 5 minutes, consider pausing the bot via
   the `/stop` endpoint and investigate the network or exchange status page.

### High Error Rate

**Symptoms:** Error rate exceeds the configured threshold (default 2%).

**Actions:**
1. Retrieve the current metrics via `/api/metrics` and confirm the error rate.
2. Inspect the `/logs` endpoint for error messages associated with order
   submissions (look for lines starting with `ERR` or `LOG {"event": "order"}`).
3. Common causes include invalid API keys, insufficient balance, or
   connectivity issues. Validate API credentials and balances on the exchange.
4. If the error rate is due to repeated order exceptions, set `GLOBAL_KILL_SWITCH=1`
   in the environment or call the `/kill` endpoint to halt trading until
   the underlying issue is resolved.

### Equity Drawdown Exceeded

**Symptoms:** The `equity_drawdown` metric surpasses the configured threshold.

**Actions:**
1. Verify that the drawdown calculation is based on up-to-date equity. The
   bot records equity snapshots on each trade; check the trade history to
   confirm large losses.
2. Review open positions via the `/api/status` endpoint. If positions are
   underwater, consider closing them manually on the exchange to limit
   further losses.
3. Assess whether recent volatility or slippage has increased risk and
   temporarily reduce position sizing or pause the strategy.
4. Adjust `EQUITY_DRAWDOWN_THRESHOLD` in the environment if the risk tolerance
   has changed.

### Position Mismatch

**Symptoms:** The bot's reported position (`/api/status`) does not match the
position visible on the exchange dashboard.

**Actions:**
1. This can occur if the bot process crashes during order execution or
   encounters an exception after placing an order. On startup, the bot
   attempts to synchronise state with the exchange.
2. Restart the bot via `/kill` then `/run` to force a fresh sync.
3. If the mismatch persists, manually reconcile positions on the exchange
   and ensure `DRY_RUN` mode reflects the desired behaviour.
4. Review the audit log (`audit.log`) for recent configuration changes.

### Overfill or Partial Fill Issues

**Symptoms:** Orders are partially filled or overfilled, resulting in
unexpected position sizes.

**Actions:**
1. Examine order parameters (size, type, price, TIF) in the trade history.
2. The bot uses a retry/backoff mechanism and may re-send orders if the
   initial attempt fails. Monitor logs to ensure duplicate orders are not
   sent inadvertently.
3. Configure the exchange with *post-only* or *reduce-only* flags via the
   UI when necessary to control execution behaviour.
4. Implement a manual circuit breaker by setting `max_positions` to 0
   temporarily to prevent new entries while positions are normalised.

### Liquidation Risk

**Symptoms:** Unrealised losses approach the maintenance margin or the
exchange issues warnings.

**Actions:**
1. Monitor the `unrealized_pnl` and `roe` fields in the `/api/status`
   response. A rapidly falling `roe` indicates heightened risk.
2. Consider closing or reducing positions early to avoid forced
   liquidation. Use the exchange's order interface to manage size.
3. Review leverage settings and adjust to a safer level. Lower leverage
   reduces liquidation risk but also limits potential returns.
4. Enable a smaller `max_positions` or larger `cooldown_sec` to slow the
   cadence of new trades during high volatility periods.

---

### Contact

For emergencies or questions not covered by this runbook, reach out to
the development team via the designated support channel.