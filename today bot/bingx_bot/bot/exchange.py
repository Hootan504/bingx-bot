from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    import ccxt  # type: ignore
except Exception:
    ccxt = None  # type: ignore

@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float

class Exchange:
    def __init__(self, symbol: str, dry_run: bool = True) -> None:
        self.symbol = symbol
        self.dry_run = dry_run
        # Primary exchange identifier. Default to BingX if unspecified.
        self.exchange_id = os.getenv("EXCHANGE_ID", "bingx").lower()
        # Optional secondary exchange for failover. If set, price and order
        # requests will fall back to this exchange when the primary fails.
        self.secondary_exchange_id = os.getenv("SECONDARY_EXCHANGE_ID", "").lower() or None
        # Secondary credentials (may fall back to primary credentials if not provided)
        self.secondary_api_key = os.getenv("SECONDARY_API_KEY") or None
        self.secondary_api_secret = os.getenv("SECONDARY_API_SECRET") or None
        self.client = self._make_client()
        # Secondary client is initialised lazily when needed to avoid
        # unnecessary connections.
        self._secondary_client = None

    def _make_client(self):
        if ccxt is None:
            return None
        try:
            api_key = os.getenv("API_KEY") or os.getenv("BINGX_API_KEY") or ""
            secret = os.getenv("API_SECRET") or os.getenv("BINGX_SECRET") or ""
            # Determine which CCXT exchange class to instantiate. Use getattr
            # to avoid attribute errors if the name does not exist.
            ex_cls_name = self.exchange_id or "bingx"
            try:
                ex_cls = getattr(ccxt, ex_cls_name)
            except AttributeError:
                ex_cls = getattr(ccxt, "bingx")  # type: ignore[attr-defined]
            # Construct default options. For Binance futures, defaultType
            # should be "future"; for BingX we set defaultType to "swap".
            opts: Dict[str, Any] = {"enableRateLimit": True}
            if ex_cls_name == "binance":
                opts["options"] = {"defaultType": "future"}
            elif ex_cls_name == "bingx":
                opts["options"] = {"defaultType": "swap"}
            ex = ex_cls({
                "apiKey": api_key,
                "secret": secret,
                **opts,
            })
            return ex
        except Exception:
            return None

    def _spot_symbol(self) -> str:
        s = self.symbol
        if ":" in s: s = s.split(":")[0]
        return s

    def get_last_price(self) -> Optional[float]:
        try:
            if self.client is not None:
                t = self.client.fetch_ticker(self._spot_symbol())
                last = t.get("last") or t.get("close")
                if last is not None: return float(last)
        except Exception:
            pass
        # Attempt failover to secondary client if configured and different
        try:
            if self.secondary_exchange_id:
                # Lazily initialise the secondary client on first use
                if self._secondary_client is None and ccxt is not None:
                    try:
                        api_key = self.secondary_api_key or os.getenv("API_KEY") or os.getenv("BINGX_API_KEY") or ""
                        secret = self.secondary_api_secret or os.getenv("API_SECRET") or os.getenv("BINGX_SECRET") or ""
                        sec_cls = getattr(ccxt, self.secondary_exchange_id)
                        opts: Dict[str, Any] = {"enableRateLimit": True}
                        if self.secondary_exchange_id == "binance":
                            opts["options"] = {"defaultType": "future"}
                        elif self.secondary_exchange_id == "bingx":
                            opts["options"] = {"defaultType": "swap"}
                        self._secondary_client = sec_cls({
                            "apiKey": api_key,
                            "secret": secret,
                            **opts,
                        })
                    except Exception:
                        self._secondary_client = None
                if self._secondary_client is not None:
                    try:
                        t = self._secondary_client.fetch_ticker(self._spot_symbol())
                        last = t.get("last") or t.get("close")
                        if last is not None:
                            return float(last)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            if ccxt is not None:
                pub = getattr(ccxt, "binance")()  # type: ignore[attr-defined]
                t = pub.fetch_ticker(self._spot_symbol())
                last = t.get("last") or t.get("close")
                if last is not None: return float(last)
        except Exception:
            pass
        # As a last resort, attempt to fetch via secondary public REST if primary REST fails
        try:
            if self.secondary_exchange_id and ccxt is not None:
                try:
                    sec_pub = getattr(ccxt, self.secondary_exchange_id)()
                    t = sec_pub.fetch_ticker(self._spot_symbol())
                    last = t.get("last") or t.get("close")
                    if last is not None:
                        return float(last)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def fetch_ohlcv(self, timeframe: str = "15m", limit: int = 200) -> Optional[List[Candle]]:
        try:
            if self.client is not None:
                rows = self.client.fetch_ohlcv(self._spot_symbol(), timeframe=timeframe, limit=limit)
                if rows:
                    out: List[Candle] = []
                    for r in rows:
                        out.append(Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)))
                    return out
        except Exception:
            pass
        try:
            import urllib.request, json as _json
            base, quote = self._spot_symbol().split("/")
            sym = f"{base}{quote}"
            url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={timeframe}&limit={limit}"
            with urllib.request.urlopen(url, timeout=6) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            out: List[Candle] = []
            for k in data:
                out.append(Candle(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
            return out
        except Exception:
            return None

    def get_balance(self) -> Optional[Dict[str, Any]]:
        if self.dry_run or self.client is None:
            return None
        try:
            bal = self.client.fetch_balance({"type": "swap"})
            total_usdt = None
            try:
                total_usdt = bal.get("total", {}).get("USDT") or bal.get("USDT", {}).get("total")
            except Exception:
                pass
            return {"total": total_usdt, "raw": bal}
        except Exception:
            return None

    def get_open_position(self) -> Optional[Dict[str, Any]]:
        if self.dry_run or self.client is None:
            return None
        try:
            fetch_positions = getattr(self.client, "fetch_positions", None)
            if fetch_positions is None:
                return None
            positions = fetch_positions([self.symbol])
            if not positions:
                return None
            for p in positions:
                size = float(p.get("contracts") or p.get("contractSize") or p.get("size") or 0)
                if abs(size) <= 0: continue
                entry = _f(p.get("entryPrice") or p.get("entry_price"))
                mark  = _f(p.get("markPrice")  or p.get("mark_price"))
                side = (p.get("side") or "").lower() or ("long" if size>0 else "short")
                lev  = p.get("leverage")
                upnl = _f(p.get("unrealizedPnl") or p.get("unrealizedProfit"))
                roe = None
                init_margin = _f(p.get("initialMargin") or p.get("initialMarginUsd"))
                if init_margin and init_margin != 0 and upnl is not None:
                    try: roe = (float(upnl)/float(init_margin))*100.0
                    except Exception: roe = None
                return {"side": side, "size": size, "entry_price": entry, "mark_price": mark, "leverage": lev, "unrealized_pnl": upnl, "roe": roe}
            return None
        except Exception:
            return None

    def create_order(self, symbol: str, side: str, type: str = 'market', amount: float = 0.0, price: Optional[float] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        params = params or {}
        # In dry-run mode we simulate an order without touching the exchange.
        if self.client is None or self.dry_run:
            return {"dry_run": True, "symbol": symbol, "side": side, "type": type, "amount": amount, "price": price, "params": params}
        # Attempt to place order on primary exchange
        try:
            ord = self.client.create_order(symbol=symbol, type=type, side=side, amount=amount, price=price, params=params)
            return {"ok": True, "order": ord}
        except Exception as e:
            # If primary fails and failover is configured, attempt on secondary exchange
            if self.secondary_exchange_id:
                try:
                    # Initialise secondary client if needed
                    if self._secondary_client is None and ccxt is not None:
                        try:
                            api_key = self.secondary_api_key or os.getenv("API_KEY") or os.getenv("BINGX_API_KEY") or ""
                            secret = self.secondary_api_secret or os.getenv("API_SECRET") or os.getenv("BINGX_SECRET") or ""
                            sec_cls = getattr(ccxt, self.secondary_exchange_id)
                            opts: Dict[str, Any] = {"enableRateLimit": True}
                            if self.secondary_exchange_id == "binance":
                                opts["options"] = {"defaultType": "future"}
                            elif self.secondary_exchange_id == "bingx":
                                opts["options"] = {"defaultType": "swap"}
                            self._secondary_client = sec_cls({
                                "apiKey": api_key,
                                "secret": secret,
                                **opts,
                            })
                        except Exception:
                            self._secondary_client = None
                    if self._secondary_client is not None:
                        try:
                            ord2 = self._secondary_client.create_order(symbol=symbol, type=type, side=side, amount=amount, price=price, params=params)
                            return {"ok": True, "order": ord2, "failover": True}
                        except Exception:
                            pass
                except Exception:
                    pass
            # Return error if all attempts fail
            return {"ok": False, "error": str(e)}

def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None or x == "" else float(x)
    except Exception:
        return None
