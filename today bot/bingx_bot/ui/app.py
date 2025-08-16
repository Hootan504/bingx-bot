from __future__ import annotations
import os, sys, json, time, threading, subprocess, shlex
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from flask import Flask, jsonify, render_template, request, send_from_directory, Response
import queue, time

# Metrics and monitoring
from ..bot.metrics import init_metrics, metrics as metrics_collector
from ..bot.monitor import start_monitor

BASE_DIR = Path(__file__).resolve().parents[2]
UI_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(UI_DIR/"templates"), static_folder=str(UI_DIR/"static"))

RUN_PROC: Optional[subprocess.Popen] = None
RUN_LOCK = threading.Lock()
LOG_BUF: List[str] = []
STATUS: Dict[str, Any] = {"dry_run": True, "price": None, "balance": None, "position": None}
CURRENT_CFG: Dict[str, Any] = {}
HIST_PATH = BASE_DIR / "trade_history.jsonl"
HIST_LOCK = threading.Lock()

# SQLite database path for trade history. We maintain a SQLite DB alongside the
# legacy JSONL file. The DB is the authoritative source for history and CSV
# export. If the JSONL file exists and the DB is empty, its contents are
# migrated on startup. This ensures backward compatibility while switching to
# SQLite for better performance and concurrency safety.
DB_PATH = BASE_DIR / "trade_history.db"

def init_db() -> None:
    """Create the trades table if it doesn't exist and migrate from the JSONL
    history file if this is the first run and the DB is empty."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER,
                symbol TEXT,
                side TEXT,
                type TEXT,
                amount REAL,
                price REAL,
                tif TEXT,
                reduce_only BOOLEAN,
                post_only BOOLEAN,
                dry_run BOOLEAN,
                ok BOOLEAN
            )
            """
        )
        conn.commit()
        # Create portfolio positions table if it doesn't exist. This table
        # stores user-defined weightings and exposure limits for multi-asset
        # portfolios. Symbol is the primary key.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_positions (
                symbol TEXT PRIMARY KEY,
                weight REAL DEFAULT 0.0,
                max_exposure REAL DEFAULT 0.0
            )
            """
        )
        conn.commit()
        # Determine if we need to migrate from JSONL. Only migrate when the DB
        # is empty to avoid duplicating records across restarts.
        cur.execute("SELECT COUNT(*) FROM trades")
        count = cur.fetchone()[0]
        if count == 0 and HIST_PATH.exists():
            try:
                with open(HIST_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        cur.execute(
                            "INSERT INTO trades (ts, symbol, side, type, amount, price, tif, reduce_only, post_only, dry_run, ok) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                d.get("ts"),
                                d.get("symbol"),
                                d.get("side"),
                                d.get("type"),
                                d.get("amount"),
                                d.get("price"),
                                d.get("tif"),
                                bool(d.get("reduce_only")),
                                bool(d.get("post_only")),
                                bool(d.get("dry_run")),
                                bool(d.get("ok")),
                            ),
                        )
                conn.commit()
            except Exception:
                # Migration errors are non-fatal; history will be empty if migration fails.
                pass
        conn.close()
    except Exception:
        # If DB initialisation fails, we silently ignore; history endpoints will handle errors.
        pass

# Initialise the database on module import
init_db()
# Initialise the global metrics collector with the trade history DB path. This
# call must occur after init_db() so that the SQLite schema is available.
init_metrics(DB_PATH)
# Start the monitoring thread. The monitor uses the global metrics collector
# to evaluate thresholds and emit alerts. It runs as a daemon thread.
start_monitor()

# SSE subscribers (one queue per client)
_SUBSCRIBERS: set[queue.Queue] = set()


@app.route("/")
def index():
    return render_template("index.html")

@app.get("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(app.static_folder, filename)

@app.get("/api/strategies")
def api_strategies():
    return jsonify({
        "sma": {"params": ["tf_fast","tf_slow","trend_fast","trend_slow"]},
        "ema": {"params": ["tf_fast","tf_slow","trend_fast","trend_slow"]},
        "rsi": {"params": ["period","overbought","oversold"]},
        "macd": {"params": ["fast","slow","signal"]},
        "composite": {"params": ["weights"]},
    })

@app.get("/api/ticker")
def api_ticker():
    import time as _t
    symbol = request.args.get("symbol", "BTC/USDT:USDT")
    price = None

    # 1) از اکسچینج (اگر ccxt موجود باشد)
    try:
        from ..bot.exchange import Exchange
        price = Exchange(symbol, dry_run=True).get_last_price()
    except Exception:
        price = None

    # 2) فالبک بایننس (چند دامنه)
    if price is None:
        try:
            import urllib.request, json as _json
            base = symbol.split('/')[0]
            quote = symbol.split('/')[1].split(':')[0]
            pair = f"{base}{quote}"
            endpoints = [
                f"https://api.binance.com/api/v3/ticker/price?symbol={pair}",
                f"https://api.binance.me/api/v3/ticker/price?symbol={pair}",
                f"https://api-gcp.binance.com/api/v3/ticker/price?symbol={pair}",
            ]
            for url in endpoints:
                try:
                    with urllib.request.urlopen(url, timeout=6) as resp:
                        data = _json.loads(resp.read().decode("utf-8"))
                    p = data.get("price")
                    if p is not None:
                        price = float(p)
                        break
                except Exception:
                    continue
        except Exception:
            price = None

    return jsonify({"symbol": symbol, "price": price, "ts": int(_t.time()*1000)})

@app.get("/api/status")
def api_status():
    return jsonify(STATUS)

@app.get("/logs")
def logs():
    return jsonify({"lines": LOG_BUF[-1000:]})


@app.get("/stream")
def stream():
    def gen(q: queue.Queue):
        try:
            # initial event
            yield 'data: {"type":"bootstrap"}\n\n'
            last_heartbeat = time.time()
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    # heartbeat
                    if time.time() - last_heartbeat >= 15:
                        yield f'data: {{"type":"heartbeat","ts":{int(time.time())}}}\n\n'
                        last_heartbeat = time.time()
        except GeneratorExit:
            pass
        finally:
            try:
                _SUBSCRIBERS.discard(q)
            except Exception:
                pass

    q = queue.Queue()
    _SUBSCRIBERS.add(q)
    return Response(gen(q), mimetype="text/event-stream", headers={"Cache-Control":"no-cache"})




@app.get("/api/history")
def api_history():
    """
    Return a slice of recent trade history from the SQLite database. The
    optional 'limit' query parameter controls how many records are returned (up
    to the most recent N trades).
    """
    limit = int(request.args.get("limit", 500))
    items: List[Dict[str, Any]] = []
    try:
        with HIST_LOCK:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # Fetch the most recent trades first, limited by the client-supplied limit.
            cur.execute(
                "SELECT ts, symbol, side, type, amount, price, tif, reduce_only, post_only, dry_run, ok FROM trades ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
            for row in rows:
                items.append({k: row[k] for k in row.keys()})
            conn.close()
    except Exception:
        # On any failure, return an empty list. Errors are swallowed to avoid breaking the UI.
        items = []
    return jsonify({"items": items, "count": len(items)})

@app.post("/api/history/clear")
def api_history_clear():
    """Delete all trade history records from both the SQLite database and legacy JSONL file."""
    try:
        with HIST_LOCK:
            # Clear the legacy JSONL file
            if HIST_PATH.exists():
                HIST_PATH.write_text("", encoding="utf-8")
            # Clear the SQLite database
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM trades")
            conn.commit()
            conn.close()
    except Exception:
        pass
    return jsonify({"ok": True})

@app.get("/api/history.csv")
def api_history_csv():
    """Stream the entire trade history as CSV from the SQLite database."""
    # Fetch all records sorted by insertion order (oldest first) so that exports
    # preserve the timeline.
    items: List[Dict[str, Any]] = []
    try:
        with HIST_LOCK:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT ts, symbol, side, type, amount, price, tif, reduce_only, post_only, dry_run, ok FROM trades ORDER BY id ASC"
            )
            rows = cur.fetchall()
            for row in rows:
                items.append({k: row[k] for k in row.keys()})
            conn.close()
    except Exception:
        items = []
    def gen():
        header = [
            "ts",
            "symbol",
            "side",
            "type",
            "amount",
            "price",
            "tif",
            "reduce_only",
            "post_only",
            "dry_run",
            "ok",
        ]
        yield ",".join(header) + "\n"
        for it in items:
            row = [
                it.get("ts"),
                it.get("symbol"),
                it.get("side"),
                it.get("type"),
                it.get("amount"),
                it.get("price"),
                it.get("tif"),
                it.get("reduce_only"),
                it.get("post_only"),
                it.get("dry_run"),
                it.get("ok"),
            ]
            yield ",".join([str(x) if x is not None else "" for x in row]) + "\n"
    return Response(
        gen(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=history.csv"},
    )

# ---------------------------------------------------------------------------
# Health check endpoint
#
# This endpoint probes several subsystems (ticker retrieval, current status
# structure, logs and history database) and returns a simple status
# dictionary. Each key is mapped to one of 'ok', 'warn' or 'err'. The UI
# uses this information to colour status badges in the health panel.
@app.get("/api/health")
def api_health():
    result: Dict[str, str] = {}
    # Ticker health: attempt to fetch last price for the currently configured
    # symbol. If no symbol is configured yet, fall back to BTC/USDT:USDT.
    try:
        from ..bot.exchange import Exchange
        sym = CURRENT_CFG.get("symbol") or "BTC/USDT:USDT"
        price = Exchange(sym, dry_run=True).get_last_price()
        result["ticker"] = "ok" if (price is not None and isinstance(price, (int, float))) else "err"
    except Exception:
        result["ticker"] = "err"
    # Status health: if the STATUS dict is non-empty we consider it ok. A
    # missing or malformed status indicates the bot hasn't yet emitted any
    # status updates.
    result["status"] = "ok" if STATUS else "err"
    # Logs health: we mark logs as ok if the buffer exists. In practice the
    # logs endpoint is always available, so this always yields ok.
    result["logs"] = "ok"
    # History health: verify that the trades table is accessible and at
    # least queryable. If the DB cannot be opened, return err.
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1 FROM trades LIMIT 1")
        conn.close()
        result["history"] = "ok"
    except Exception:
        result["history"] = "err"
    return jsonify(result)


# ---------------------------------------------------------------------------
# Metrics endpoint
#
# This endpoint exposes internal metrics collected by the bot. The metrics
# include order latency, error rate, WebSocket reconnect count, average price
# drift and drawdown statistics. Clients can poll this endpoint to display
# runtime analytics and inform dashboards.
@app.get("/api/metrics")
def api_metrics():
    try:
        mc = metrics_collector or init_metrics(DB_PATH)
        data = mc.get_metrics() if mc else {}
        return jsonify(data)
    except Exception:
        return jsonify({})

# ---------------------------------------------------------------------------
# Portfolio endpoints
#
# These endpoints provide CRUD operations for user-defined portfolio
# positions. The positions table stores symbol, weight and maximum
# exposure. We expose endpoints to list all positions, add/update a
# position and remove a position.


@app.get("/api/portfolio")
def api_portfolio_get():
    items: List[Dict[str, Any]] = []
    try:
        with HIST_LOCK:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT symbol, weight, max_exposure FROM portfolio_positions ORDER BY symbol ASC")
            rows = cur.fetchall()
            for row in rows:
                items.append({k: row[k] for k in row.keys()})
            conn.close()
    except Exception:
        items = []
    return jsonify({"items": items, "count": len(items)})


@app.post("/api/portfolio")
def api_portfolio_post():
    data = request.get_json(force=True) or {}
    sym = str(data.get("symbol")) if data.get("symbol") else None
    weight = data.get("weight")
    max_exposure = data.get("max_exposure")
    if not sym:
        return jsonify({"ok": False, "error": "symbol required"}), 400
    try:
        with HIST_LOCK:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO portfolio_positions (symbol, weight, max_exposure) VALUES (?,?,?)",
                (
                    sym.upper(),
                    float(weight) if weight is not None else 0.0,
                    float(max_exposure) if max_exposure is not None else 0.0,
                ),
            )
            conn.commit()
            conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.delete("/api/portfolio")
def api_portfolio_delete():
    sym = request.args.get("symbol") or request.get_json(force=False, silent=True) or None
    if not sym:
        return jsonify({"ok": False, "error": "symbol required"}), 400
    try:
        with HIST_LOCK:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("DELETE FROM portfolio_positions WHERE symbol = ?", (str(sym).upper(),))
            conn.commit()
            conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/api/backtest")
def api_backtest():
    data = request.get_json(force=True) or {}
    symbol = data.get("symbol", "BTC/USDT:USDT")
    timeframe = data.get("timeframe", "15m")
    bars = int(data.get("lookback") or data.get("bars") or 500)
    start_cash = float(data.get("bt_cash") or 10000)
    usd_per_trade = float(data.get("usd_per_trade") or 50)
    fee_taker_pct = float(data.get("fee_taker") or 0.05) / 100.0
    strategy = (data.get("strategy") or "sma").lower()
    params = data.get("params") or {}

    from ..bot.exchange import Exchange
    ex = Exchange(symbol, dry_run=True)
    candles = ex.fetch_ohlcv(timeframe, limit=bars) or []
    if not candles or len(candles) < 50:
        return jsonify({"ok": False, "error": "Not enough candles"}), 400

    closes = [c.close for c in candles]
    times  = [c.timestamp for c in candles]

    def sma(vals,p):
        out=[None]*len(vals); s=0.0
        for i,v in enumerate(vals):
            s+=v
            if i>=p: s-=vals[i-p]
            if i>=p-1: out[i]=s/p
        return out
    def ema(vals,p):
        out=[None]*len(vals); k=2/(p+1); e=None
        for i,v in enumerate(vals):
            if e is None:
                if i>=p-1: e=sum(vals[i-p+1:i+1])/p
            else: e=v*k+e*(1-k)
            out[i]=e
        return out
    def rsi(vals,period=14):
        n=len(vals); out=[None]*n
        if n<period+1: return out
        g=l=0.0
        for i in range(1,period+1):
            d=vals[i]-vals[i-1]
            if d>=0: g+=d
            else: l+=-d
        ag=g/period; al=l/period
        out[period]=100.0 if al==0 else 100-100/(1+(ag/al if al!=0 else 1e9))
        for i in range(period+1,n):
            d=vals[i]-vals[i-1]; gp=max(d,0.0); lp=max(-d,0.0)
            ag=(ag*(period-1)+gp)/period
            al=(al*(period-1)+lp)/period
            out[i]=100.0 if al==0 else 100-100/(1+(ag/al))
        return out
    def macd(vals, fast=12, slow=26, sig=9):
        ef=ema(vals,fast); es=ema(vals,slow)
        m=[(a-b) if (a is not None and b is not None) else None for a,b in zip(ef,es)]
        s=ema([x if x is not None else 0.0 for x in m], sig)
        h=[(mm-ss) if (mm is not None and ss is not None) else None for mm,ss in zip(m,s)]
        return m,s,h

    rsi_p=int(params.get("period") or 14)
    rsi_ob=float(params.get("overbought") or 70)
    rsi_os=float(params.get("oversold") or 30)
    macd_fast=int(params.get("fast") or 12)
    macd_slow=int(params.get("slow") or 26)
    macd_sig=int(params.get("signal") or 9)
    sma_fast=int(params.get("tf_fast") or 9)
    sma_slow=int(params.get("tf_slow") or 21)
    ema_fast=int(params.get("tf_fast") or 9)
    ema_slow=int(params.get("tf_slow") or 21)

    SMAF=sma(closes,sma_fast); SMAS=sma(closes,sma_slow)
    EMAF=ema(closes,ema_fast); EMAS=ema(closes,ema_slow)
    RSI=rsi(closes,rsi_p); M,S,H=macd(closes,macd_fast,macd_slow,macd_sig)

    def sig_at(i):
        if i==0: return None
        if strategy=="sma":
            a1,b1,a2,b2 = SMAF[i-1],SMAS[i-1],SMAF[i],SMAS[i]
            if None in (a1,b1,a2,b2): return None
            if a1<=b1 and a2>b2: return "long"
            if a1>=b1 and a2<b2: return "short"
            return None
        if strategy=="ema":
            a1,b1,a2,b2 = EMAF[i-1],EMAS[i-1],EMAF[i],EMAS[i]
            if None in (a1,b1,a2,b2): return None
            if a1<=b1 and a2>b2: return "long"
            if a1>=b1 and a2<b2: return "short"
            return None
        if strategy=="rsi":
            r1,r2 = RSI[i-1],RSI[i]
            if r1 is None or r2 is None: return None
            if r1<=rsi_os and r2>rsi_os: return "long"
            if r1>=rsi_ob and r2<rsi_ob: return "short"
            return None
        if strategy=="macd":
            m1,s1,m2,s2 = M[i-1],S[i-1],M[i],S[i]
            if None in (m1,s1,m2,s2): return None
            if m1<=s1 and m2>s2: return "long"
            if m1>=s1 and m2<s2: return "short"
            return None
        # composite (رأی‌گیری ساده بین 4 اندیکاتور)
        votes=0
        a1,b1,a2,b2 = SMAF[i-1],SMAS[i-1],SMAF[i],SMAS[i]
        if not None in (a1,b1,a2,b2):
            if a1<=b1 and a2>b2: votes+=1
            if a1>=b1 and a2<b2: votes-=1
        a1,b1,a2,b2 = EMAF[i-1],EMAS[i-1],EMAF[i],EMAS[i]
        if not None in (a1,b1,a2,b2):
            if a1<=b1 and a2>b2: votes+=1
            if a1>=b1 and a2<b2: votes-=1
        r1,r2 = RSI[i-1],RSI[i]
        if r1 is not None and r2 is not None:
            if r1<=rsi_os and r2>rsi_os: votes+=1
            if r1>=rsi_ob and r2<rsi_ob: votes-=1
        m1,s1,m2,s2 = M[i-1],S[i-1],M[i],S[i]
        if not None in (m1,s1,m2,s2):
            if m1<=s1 and m2>s2: votes+=1
            if m1>=s1 and m2<s2: votes-=1
        if votes>0: return "long"
        if votes<0: return "short"
        return None

    equity=start_cash; peak=start_cash; max_dd=0.0; pos=None; trades=[]
    def fee(v): return v*fee_taker_pct

    for i in range(1,len(candles)):
        p=closes[i]; s=sig_at(i)
        if pos and s and ((pos['side']=="long" and s=="short") or (pos['side']=="short" and s=="long")):
            exit_val=pos['qty']*p
            pnl_gross=(p-pos['entry'])*pos['qty'] if pos['side']=="long" else (pos['entry']-p)*pos['qty']
            pnl=pnl_gross - fee(pos['val']) - fee(exit_val)
            equity+=pnl
            trades.append({"entry_ts":pos['ts'],"exit_ts":times[i],"side":pos['side'],"entry":pos['entry'],"exit":p,"pnl":pnl})
            pos=None
        if not pos and s in ("long","short"):
            val=usd_per_trade
            if val>0:
                qty=val/p
                pos={"side":s,"entry":p,"qty":qty,"val":val,"ts":times[i]}
                equity-=fee(val)
        if equity>peak: peak=equity
        dd=peak-equity
        if dd>max_dd: max_dd=dd

    if pos:
        p=closes[-1]; exit_val=pos['qty']*p
        pnl_gross=(p-pos['entry'])*pos['qty'] if pos['side']=="long" else (pos['entry']-p)*pos['qty']
        pnl=pnl_gross - fee(pos['val']) - fee(exit_val)
        equity+=pnl
        trades.append({"entry_ts":pos['ts'],"exit_ts":times[-1],"side":pos['side'],"entry":pos['entry'],"exit":p,"pnl":pnl})
        pos=None

    wins=sum(1 for t in trades if t["pnl"]>0)
    losses=len(trades)-wins
    winrate=(wins/max(1,len(trades)))*100.0
    net_pnl=sum(t["pnl"] for t in trades)

    import math
    rets=[]
    for t in trades:
        denom = usd_per_trade if usd_per_trade>0 else 1.0
        rets.append(t["pnl"]/denom)
    if len(rets)>=2:
        mu=sum(rets)/len(rets)
        var=sum((x-mu)**2 for x in rets)/(len(rets)-1)
        sd=math.sqrt(max(1e-12,var))
        sharpe=mu/sd*(len(rets)**0.5)
    else:
        sharpe=0.0

    return jsonify({"ok":True,"summary":{
        "trades":len(trades),"wins":wins,"losses":losses,"winrate":winrate,
        "net_pnl":net_pnl,"start_equity":start_cash,"final_equity":equity,
        "max_drawdown":max_dd,"sharpe":sharpe
    },"trades":trades})

@app.post("/run")
def run_bot():
    global RUN_PROC, CURRENT_CFG
    data: Dict[str, Any] = request.get_json(force=True) or {}

    # Global kill switch: if set via environment, refuse to start any bots.
    if os.getenv("GLOBAL_KILL_SWITCH") in ("1", "true", "True"):  # type: ignore
        return jsonify({"ok": False, "error": "Global kill switch is active"}), 403
    CURRENT_CFG = dict(data)
    STATUS["dry_run"] = bool(data.get("dry_run", True))

    args = [sys.executable, "-m", "bingx_bot.bot.main",
            "--symbol", str(data.get("symbol","BTC/USDT:USDT")),
            "--timeframe", str(data.get("timeframe","15m")),
            "--trend_tf", str(data.get("trend_tf","4h")),
            "--strategy", str(data.get("strategy","composite")),
            "--usd_per_trade", str(data.get("usd_per_trade",50)),
            "--sleep", str(data.get("sleep",30))]
    if data.get("dry_run", True): args.append("--dry_run")
    if data.get("loop", True): args.append("--loop")

    env = os.environ.copy()
    env["EXCHANGE_ID"] = str(data.get("exchange_id","bingx"))
    # Pass secondary exchange and credentials to the child process if provided
    if data.get("secondary_exchange_id"):
        env["SECONDARY_EXCHANGE_ID"] = str(data.get("secondary_exchange_id"))
    if data.get("secondary_api_key"):
        env["SECONDARY_API_KEY"] = str(data.get("secondary_api_key"))
    if data.get("secondary_api_secret"):
        env["SECONDARY_API_SECRET"] = str(data.get("secondary_api_secret"))
    if data.get("api_key"): env["API_KEY"] = str(data.get("api_key"))
    if data.get("api_secret"): env["API_SECRET"] = str(data.get("api_secret"))
    env["BOT_CONFIG_JSON"] = json.dumps(data)
    # Pass trading profile (paper/shadow/live-small/live-normal) to the child via env
    if data.get("profile"):
        env["TRADER_PROFILE"] = str(data.get("profile"))

    # Write an audit log entry capturing who started the bot and the selected
    # configuration. This log can be used to trace configuration changes over
    # time. We deliberately capture limited information (timestamp, remote
    # address, config) to avoid storing sensitive secrets.
    try:
        import datetime as _dt
        audit_entry = {
            "ts": int(time.time()),
            "iso_ts": _dt.datetime.utcnow().isoformat() + "Z",
            "remote_addr": request.remote_addr,
            "config": {k: data.get(k) for k in data.keys() if k not in ("api_key", "api_secret")}
        }
        audit_path = BASE_DIR / "audit.log"
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    with RUN_LOCK:
        stop_proc_locked()
        LOG_BUF.clear()
        LOG_BUF.append("Starting: " + " ".join(shlex.quote(a) for a in args))
        LOG_BUF.append(f"> cwd: {BASE_DIR}")
        try:
            RUN_PROC = subprocess.Popen(args, cwd=str(BASE_DIR), env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        bufsize=1, universal_newlines=True)
            threading.Thread(target=read_logs, daemon=True).start()
            return jsonify({"ok": True, "pid": RUN_PROC.pid})
        except Exception as e:
            LOG_BUF.append(f"ERROR: {e}")
            return jsonify({"ok": False, "error": str(e)}), 500

@app.post("/stop")
def stop_bot():
    with RUN_LOCK:
        stop_proc_locked()
    return jsonify({"ok": True})

@app.post("/kill")
def kill_switch():
    with RUN_LOCK:
        stop_proc_locked()
    return jsonify({"ok": True})

def stop_proc_locked():
    global RUN_PROC
    if RUN_PROC and RUN_PROC.poll() is None:
        try: RUN_PROC.terminate()
        except Exception: pass
        try: RUN_PROC.kill()
        except Exception: pass
    RUN_PROC = None


def read_logs():
    global RUN_PROC
    while RUN_PROC and RUN_PROC.stdout and RUN_PROC.poll() is None:
        line = RUN_PROC.stdout.readline()
        if not line:
            break
        s = line.rstrip()
        if s.startswith("STATUS "):
            try:
                d = json.loads(s[7:])
                if isinstance(d, dict):
                    if "price" in d:
                        STATUS["price"] = d["price"]
                    if "balance" in d:
                        STATUS["balance"] = d["balance"]
                    if "position" in d:
                        STATUS["position"] = d["position"]
            except Exception:
                pass
            # Notify SSE subscribers about status update
            try:
                msg = 'data: {"type":"status_update"}\n\n'
                for __q in list(_SUBSCRIBERS):
                    try:
                        __q.put_nowait(msg)
                    except Exception:
                        _SUBSCRIBERS.discard(__q)
            except Exception:
                pass
        elif s.startswith("LOG "):
            try:
                d = json.loads(s[4:])
                if isinstance(d, dict) and d.get("event") == "order":
                    res = d.get("result") or {}
                    item = {
                        "ts": int(time.time() * 1000),
                        "symbol": res.get("symbol"),
                        "side": res.get("side"),
                        "type": res.get("type"),
                        "amount": (res.get("amount") if isinstance(res.get("amount"), (int,float)) else (res.get("order") or {}).get("amount")),
                        "price": (res.get("price") if isinstance(res.get("price"), (int,float)) else (res.get("order") or {}).get("price")),
                        "params": res.get("params"),
                        "reduce_only": (res.get("params") or {}).get("reduceOnly"),
                        "post_only": (res.get("params") or {}).get("postOnly"),
                        "tif": (res.get("params") or {}).get("timeInForce"),
                        "dry_run": bool(res.get("dry_run", STATUS.get("dry_run", True))),
                        "ok": res.get("ok", True)
                    }
                    try:
                        # Persist the trade record to both the SQLite database and the legacy JSONL file.
                        with HIST_LOCK:
                            # Insert into SQLite
                            try:
                                conn = sqlite3.connect(DB_PATH)
                                cur = conn.cursor()
                                cur.execute(
                                    "INSERT INTO trades (ts, symbol, side, type, amount, price, tif, reduce_only, post_only, dry_run, ok) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                    (
                                        item.get("ts"),
                                        item.get("symbol"),
                                        item.get("side"),
                                        item.get("type"),
                                        item.get("amount"),
                                        item.get("price"),
                                        item.get("tif"),
                                        bool(item.get("reduce_only")),
                                        bool(item.get("post_only")),
                                        bool(item.get("dry_run")),
                                        bool(item.get("ok")),
                                    ),
                                )
                                conn.commit()
                                conn.close()
                            except Exception:
                                pass
                            # Append to the JSONL file for backwards compatibility
                            try:
                                with open(HIST_PATH, "a", encoding="utf-8") as f:
                                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                            except Exception:
                                pass
                    except Exception:
                        pass
                    # Notify SSE subscribers about history update
                    try:
                        msg = 'data: {"type":"history_update"}\n\n'
                        for __q in list(_SUBSCRIBERS):
                            try:
                                __q.put_nowait(msg)
                            except Exception:
                                _SUBSCRIBERS.discard(__q)
                    except Exception:
                        pass
            except Exception:
                pass
        LOG_BUF.append(s)
        if len(LOG_BUF) > 5000:
            del LOG_BUF[:len(LOG_BUF) - 5000]

@app.after_request
def no_cache(resp):
    p = request.path or ""
    if p.startswith("/api/") or p.startswith("/logs"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=5000)
    a = p.parse_args()
    app.run(host=a.host, port=a.port, debug=False, use_reloader=False, threaded=True)
