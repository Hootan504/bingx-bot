"""Monitoring and alerting utilities for the trading bot.

This module defines a background monitoring thread that periodically reads
metrics from the global metrics collector and triggers alerts when they
exceed configured thresholds. Alerts are currently implemented as simple
log messages printed to stdout. In a production deployment you would
replace the notify() function with integrations to Telegram, email or
other notification channels.
"""
from __future__ import annotations

import threading
import time
import os
from typing import Dict, Any

from .metrics import metrics as global_metrics


# Default alert thresholds. These can be overridden by environment
# variables for runtime configuration.
DEFAULT_THRESHOLDS = {
    'error_rate': 0.02,          # 2% errors per order submissions
    'ws_reconnects': 10,         # number of WS reconnects per monitor interval
    'equity_drawdown': 0.05,     # 5% drawdown in equity
}


def get_thresholds() -> Dict[str, float]:
    """Read alert thresholds from environment variables or use defaults."""
    thresholds = DEFAULT_THRESHOLDS.copy()
    try:
        if os.getenv('ERROR_RATE_THRESHOLD'):
            thresholds['error_rate'] = float(os.getenv('ERROR_RATE_THRESHOLD'))
        if os.getenv('WS_RECONNECT_THRESHOLD'):
            thresholds['ws_reconnects'] = float(os.getenv('WS_RECONNECT_THRESHOLD'))
        if os.getenv('EQUITY_DRAWDOWN_THRESHOLD'):
            thresholds['equity_drawdown'] = float(os.getenv('EQUITY_DRAWDOWN_THRESHOLD'))
    except Exception:
        # Ignore malformed environment variables
        pass
    return thresholds


def _send_telegram(msg: str) -> bool:
    """Attempt to send a Telegram message.

    Reads the bot token and chat ID from environment variables
    (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID). Returns True on
    success, False otherwise. All errors are caught silently to
    avoid crashing the monitor thread.
    """
    import os
    import urllib.parse
    import urllib.request
    token = os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or ""
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        # short timeout to avoid blocking
        with urllib.request.urlopen(req, timeout=5) as _resp:
            return True
    except Exception:
        return False


def _send_email(subject: str, body: str) -> bool:
    """Attempt to send an email alert.

    Requires EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD and
    EMAIL_TO environment variables to be set. Uses TLS via SMTP. Returns
    True on success, False otherwise. All errors are caught.
    """
    import os
    import smtplib
    from email.mime.text import MIMEText
    host = os.getenv("EMAIL_HOST") or ""
    port = os.getenv("EMAIL_PORT") or ""
    user = os.getenv("EMAIL_USER") or ""
    passwd = os.getenv("EMAIL_PASSWORD") or ""
    to_addr = os.getenv("EMAIL_TO") or ""
    if not host or not port or not user or not passwd or not to_addr:
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_addr
        with smtplib.SMTP(host, int(port), timeout=5) as server:
            server.starttls()
            server.login(user, passwd)
            server.sendmail(user, [to_addr], msg.as_string())
        return True
    except Exception:
        return False


def notify(alert_type: str, message: str) -> None:
    """Send an alert via available channels.

    This function first attempts to send the alert over Telegram if
    configured. If that fails or is not configured, it then tries
    email. As a last resort it logs to stdout. All exceptions are
    swallowed to keep monitoring thread resilient.
    """
    alert_msg = f"{alert_type.upper()}: {message}"
    try:
        # Try Telegram first
        if _send_telegram(alert_msg):
            return
        # Then email
        subject = f"Trading Bot Alert: {alert_type}"
        if _send_email(subject, alert_msg):
            return
    except Exception:
        # ignore any exceptions in sending logic
        pass
    # Fallback to stdout
    try:
        print(f"[ALERT] {alert_msg}")
    except Exception:
        pass


_monitor_started: bool = False


def check_thresholds(metrics_data: Dict[str, Any], thresholds: Dict[str, float]) -> None:
    """Evaluate metrics against thresholds and emit alerts when breached."""
    try:
        if metrics_data is None:
            return
        # Error rate threshold
        er = metrics_data.get('order_error_rate')
        if er is not None and er > thresholds.get('error_rate', 0.0):
            notify('error_rate', f"Error rate {er:.2%} exceeds threshold {thresholds['error_rate']:.2%}")
        # WebSocket reconnect threshold (per interval). The collector accumulates
        # reconnects; if the count exceeds the threshold within the interval
        # between checks an alert is triggered and the counter is reset to
        # avoid repeated alerts.
        reconnects = metrics_data.get('ws_reconnects')
        if reconnects is not None and reconnects > thresholds.get('ws_reconnects', float('inf')):
            notify('ws_reconnects', f"WS reconnects {reconnects} in interval exceeds threshold {thresholds['ws_reconnects']}")
            # reset counter to avoid duplicate alerts
            global_metrics.ws_reconnects = 0  # type: ignore
        # Equity drawdown threshold
        dd = metrics_data.get('equity_drawdown')
        if dd is not None and thresholds.get('equity_drawdown') is not None:
            threshold_dd = thresholds['equity_drawdown']
            # If drawdown is absolute value > threshold * peak, treat as alert
            if dd > threshold_dd:
                notify('equity_drawdown', f"Drawdown {dd:.2f} exceeds threshold {threshold_dd:.2f}")
    except Exception:
        pass


def start_monitor(interval: float = 60.0) -> None:
    """Start the monitoring thread if not already running.

    The thread sleeps for the specified interval (default 60 seconds), then
    reads metrics from the global collector and evaluates them against
    thresholds. Alerts are logged via notify().
    """
    global _monitor_started
    if _monitor_started:
        return
    thresholds = get_thresholds()
    _monitor_started = True

    def monitor_loop() -> None:
        while True:
            try:
                mc = global_metrics
                if mc is not None:
                    data = mc.get_metrics()
                    check_thresholds(data, thresholds)
                time.sleep(interval)
            except Exception:
                # never exit the loop on exceptions
                try:
                    time.sleep(interval)
                except Exception:
                    pass

    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()