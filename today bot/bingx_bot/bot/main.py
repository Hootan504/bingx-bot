from __future__ import annotations
import os, json, argparse
from .trader import Trader

def get_config_from_env() -> dict:
    raw = os.environ.get("BOT_CONFIG_JSON")
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', required=True)
    ap.add_argument('--timeframe', default='15m')
    ap.add_argument('--trend_tf', default='4h')
    ap.add_argument('--strategy', default='composite')
    ap.add_argument('--usd_per_trade', type=float, default=50.0)
    ap.add_argument('--sleep', type=float, default=30.0)
    ap.add_argument('--dry_run', action='store_true')
    ap.add_argument('--loop', action='store_true')
    args = ap.parse_args()

    cfg = get_config_from_env()
    cfg.update({
        'symbol': args.symbol,
        'timeframe': args.timeframe,
        'trend_tf': args.trend_tf,
        'strategy': args.strategy,
        'usd_per_trade': args.usd_per_trade,
        'sleep': args.sleep,
        'dry_run': bool(args.dry_run),
        'loop': bool(args.loop),
    })

    t = Trader(cfg)
    t.run()

if __name__ == '__main__':
    main()
