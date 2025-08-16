(function(){
  const $ = (s)=>document.querySelector(s);
  const jf = (o)=>JSON.stringify(o);
  const jp = (s)=>{ try{ return JSON.parse(s); }catch(_){ return null; } };
  const num = (v,d=null)=>{ const n=Number(v); return Number.isFinite(n)?n:d; };
  const fmt = (x,fd=2)=> new Intl.NumberFormat('en-US',{maximumFractionDigits:fd}).format(x);
  const SKEY = 'bingx_profile_full_v1';

  async function getJSON(url, signal){
    const r = await fetch(url, {cache:'no-store', signal});
    if(!r.ok) throw new Error(r.status+' '+r.statusText);
    return r.json();
  }

  const toPair = (sym)=>{ try{ const base=sym.split('/')[0]; const quote=sym.split('/')[1].split(':')[0]; return base+quote; }catch(_){ return 'BTCUSDT'; } };
  const tfToTv = (tf)=>{ const m=String(tf||'15m').match(/^(\d+)([mh])$/i); if(!m) return '15'; const v=+m[1]; return m[2].toLowerCase()==='h'?String(v*60):String(v); };
  function refreshTV(){
    const sym=$('#symbol')?.value?.trim()||'BTC/USDT:USDT';
    const tf=$('#timeframe')?.value?.trim()||'15m';
    const tv=$('#tv-frame'); if(!tv) return;
    const url=`https://s.tradingview.com/widgetembed/?symbol=${encodeURIComponent('BINANCE:'+toPair(sym))}&interval=${encodeURIComponent(tfToTv(tf))}&theme=dark&hide_legend=1&autosize=1`;
    if(tv.src!==url) tv.src=url;
  }

  function showParamsFor(strategy){ ['sma','ema','rsi','macd'].forEach(id=>{ const el=document.getElementById('params-'+id); if(el) el.hidden=(strategy!==id); }); }
  const normW=(a,b,c,d)=>{ let s=a+b+c+d; if(!s) return [25,25,25,25]; return [a/s*100,b/s*100,c/s*100,d/s*100].map(x=>Math.round(x)); };

  function profileCollect(){
    const w=normW(num($('#w_sma')?.value,25),num($('#w_ema')?.value,25),num($('#w_rsi')?.value,25),num($('#w_macd')?.value,25));
    return {
      symbol: $('#symbol')?.value?.trim()||'BTC/USDT:USDT',
      timeframe: $('#timeframe')?.value?.trim()||'15m',
      trend_tf: $('#trend_tf')?.value?.trim()||'4h',
      strategy: $('#strategy')?.value||'composite',
      usd_per_trade: num($('#usd_per_trade')?.value,50),
      dry_run: !!$('#dry_run')?.checked,
      loop: !!$('#loop')?.checked,
      sleep: num($('#sleep')?.value,30),
      ps_mode: $('#ps_mode')?.value||'fixed',
      ps_value: num($('#ps_value')?.value,50),
      leverage: num($('#leverage')?.value,5),
      margin_mode: $('#margin_mode')?.value||'isolated',
      sl_pct: num($('#sl_pct')?.value),
      tp1_pct: num($('#tp1_pct')?.value),
      tp2_pct: num($('#tp2_pct')?.value),
      tp3_pct: num($('#tp3_pct')?.value),
      trail_pct: num($('#trail_pct')?.value),
      daily_loss_pct: num($('#daily_loss_pct')?.value),
      max_positions: num($('#max_positions')?.value,1),
      order_type: $('#order_type')?.value||'market',
      tif: $('#tif')?.value||'GTC',
      reduce_only: !!$('#reduce_only')?.checked,
      post_only: !!$('#post_only')?.checked,
      slippage_pct: num($('#slippage_pct')?.value,0.2),
      cooldown_sec: num($('#cooldown_sec')?.value,30),
      min_volume: num($('#min_volume')?.value),
      max_atr_pct: num($('#max_atr_pct')?.value),
      session_start: $('#session_start')?.value||'',
      session_end: $('#session_end')?.value||'',
      whitelist: ($('#whitelist')?.value||'').trim(),
      weights: {sma:w[0],ema:w[1],rsi:w[2],macd:w[3]},
      lookback: num($('#lookback')?.value,300),
      fee_maker: num($('#fee_maker')?.value,0.02),
      fee_taker: num($('#fee_taker')?.value,0.05),
      funding_pct: num($('#funding_pct')?.value,0.01),
      log_level: $('#log_level')?.value||'info',
      webhook_url: $('#webhook_url')?.value||'',
      sound_on: !!$('#sound_on')?.checked,
      exchange_id: $('#exchange_id')?.value||'bingx',
      testnet: !!$('#testnet')?.checked,
      api_key: $('#api_key')?.value||'',
      api_secret: $('#api_secret')?.value||'',
      profile_name: $('#profile_name')?.value||'',
      _ts: Date.now()
    };
  }

  function profileApply(p){
    if(!p) return;
    const set=(id,val)=>{ const el=$(id); if(!el) return; if(el.type==='checkbox') el.checked=!!val; else el.value=(val??''); };
    set('#symbol',p.symbol); set('#timeframe',p.timeframe); set('#trend_tf',p.trend_tf);
    set('#strategy',p.strategy); set('#usd_per_trade',p.usd_per_trade);
    set('#dry_run',p.dry_run); set('#loop',p.loop); set('#sleep',p.sleep);
    set('#ps_mode',p.ps_mode); set('#ps_value',p.ps_value);
    set('#leverage',p.leverage); set('#margin_mode',p.margin_mode);
    set('#sl_pct',p.sl_pct); set('#tp1_pct',p.tp1_pct); set('#tp2_pct',p.tp2_pct); set('#tp3_pct',p.tp3_pct);
    set('#trail_pct',p.trail_pct); set('#daily_loss_pct',p.daily_loss_pct); set('#max_positions',p.max_positions);
    set('#order_type',p.order_type); set('#tif',p.tif); set('#reduce_only',p.reduce_only); set('#post_only',p.post_only);
    set('#slippage_pct',p.slippage_pct); set('#cooldown_sec',p.cooldown_sec);
    set('#min_volume',p.min_volume); set('#max_atr_pct',p.max_atr_pct);
    set('#session_start',p.session_start); set('#session_end',p.session_end);
    set('#whitelist',p.whitelist);
    if(p.weights){ set('#w_sma',p.weights.sma); set('#w_ema',p.weights.ema); set('#w_rsi',p.weights.rsi); set('#w_macd',p.weights.macd);
      $('#w_sma_val').textContent=p.weights.sma+'%'; $('#w_ema_val').textContent=p.weights.ema+'%'; $('#w_rsi_val').textContent=p.weights.rsi+'%'; $('#w_macd_val').textContent=p.weights.macd+'%'; }
    set('#lookback',p.lookback); set('#fee_maker',p.fee_maker); set('#fee_taker',p.fee_taker); set('#funding_pct',p.funding_pct);
    set('#log_level',p.log_level); set('#webhook_url',p.webhook_url); set('#sound_on',p.sound_on);
    set('#exchange_id',p.exchange_id); set('#testnet',p.testnet);
    set('#api_key',p.api_key); set('#api_secret',p.api_secret);
    set('#profile_name',p.profile_name);
    showParamsFor($('#strategy').value); refreshTV();
  }
  const save=()=>{ try{ localStorage.setItem(SKEY, jf(profileCollect())); }catch(_){ } };
  const load=()=>{ try{ return jp(localStorage.getItem(SKEY)); }catch(_){ return null; } };
  const reset=()=>{ try{ localStorage.removeItem(SKEY); }catch(_){ } };
  const debounce=(fn,ms=250)=>{ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); }; };

  async function loadStrategies(){
    const sel = $('#strategy'); if(!sel) return;
    try{
      const r=await fetch('/api/strategies',{cache:'no-store'});
      const data=await r.json(); const list=Object.keys(data||{});
      const cur=sel.value; if(list.length){ sel.innerHTML=''; list.forEach(n=>{ const o=document.createElement('option'); o.value=n; o.textContent=n; sel.appendChild(o); }); if(list.includes(cur)) sel.value=cur; }
    }catch(_){}
    showParamsFor(sel.value);
  }
  async function refreshPriceOnce(signal){
    const sym=$('#symbol')?.value?.trim()||'BTC/USDT:USDT';
    const d=await getJSON(`/api/ticker?symbol=${encodeURIComponent(sym)}&t=${Date.now()}`, signal);
    if(typeof d?.price==='number'){
      const p=fmt(d.price,2);
      $('#live-price') && ($('#live-price').textContent=p);
      $('#ac-price') && ($('#ac-price').textContent=p);
    }
  }
  async function refreshStatusOnce(signal){
    const s=await getJSON(`/api/status?t=${Date.now()}`, signal);
    $('#api-mode') && ($('#api-mode').textContent = s?.dry_run ? 'dry-run':'real');
    if(typeof s?.price==='number'){ $('#ac-price') && ($('#ac-price').textContent=fmt(s.price,2)); }
    if(s?.balance && s.balance.total!=null){ $('#ac-balance') && ($('#ac-balance').textContent=String(s.balance.total)); }
    const P=s?.position||{}; const put=(id,v)=>{ const el=$(id); if(el) el.textContent=(v==null||v==='')?'—':String(v); };
    put('#pos-side',P.side); put('#pos-size',P.size); put('#pos-entry',P.entry_price); put('#pos-mark',P.mark_price);
    put('#pos-lev',P.leverage); put('#pos-pnl',P.unrealized_pnl);
    const rv=Number(P.roe); put('#pos-roe',Number.isFinite(rv)?rv.toFixed(2)+'%':'—');
  }
  async function refreshLogsOnce(signal){
    const d=await getJSON(`/logs?t=${Date.now()}`, signal);
    const lines=Array.isArray(d?.lines)?d.lines:[];
    const el=$('#logs'); if(el){ el.textContent=lines.join('\n'); el.scrollTop=el.scrollHeight; }
  }
  async function refreshHistoryOnce(signal){
    const tbody=$('#history-tbody'); const cnt=$('#history-count');
    if(!tbody && !cnt) return;
    const d=await getJSON(`/api/history?limit=500&t=${Date.now()}`, signal);
    const items=Array.isArray(d?.items)?d.items:[];
    if(cnt) cnt.textContent=String(items.length);
    if(!tbody) return;
    tbody.innerHTML='';
    for(const it of items){
      const tr=document.createElement('tr');
      const ts = it.ts ? new Date(it.ts).toLocaleString() : '—';
      const cols=[ts,it.symbol??'—',it.side??'—',it.type??'—',
        it.amount!=null?fmt(it.amount,6):'—',
        it.price!=null?fmt(it.price,2):'—',
        it.tif??'—',it.reduce_only?'yes':'no',it.post_only?'yes':'no',it.dry_run?'dry':'real',it.ok===false?'fail':'ok'];
      cols.forEach(v=>{ const td=document.createElement('td'); td.textContent=String(v); tr.appendChild(td); });
      tbody.appendChild(tr);
    }
  }

  // Poll the health endpoint and update the health panel badges.
  async function refreshHealthOnce(signal){
    try{
      const d = await getJSON(`/api/health?t=${Date.now()}`, signal);
      const keys=['ticker','status','logs','history'];
      for(const k of keys){
        const el=document.getElementById(`health-${k}`);
        if(!el) continue;
        const v = (d && typeof d[k] === 'string') ? d[k] : 'err';
        el.textContent = v;
        el.classList.remove('ok','warn','err');
        if(v==='ok') el.classList.add('ok'); else if(v==='warn') el.classList.add('warn'); else el.classList.add('err');
      }
    }catch(_){/* ignore */}
  }

  async function runBacktest(){
    const put=(id,v)=>{ const el=$(id); if(el) el.textContent=v; };
    const tbody=$('#bt-rows'); if(tbody) tbody.innerHTML='';
    const p=profileCollect();
    p.bars = Number($('#bt_bars')?.value||500);
    p.bt_cash = Number($('#bt_cash')?.value||10000);
    try{
      const r=await fetch('/api/backtest',{method:'POST',headers:{'Content-Type':'application/json'},body:jf(p)});
      const d=await r.json();
      if(!r.ok || d.ok===false){ alert('Backtest failed: '+(d.error||r.statusText)); return; }
      const s=d.summary||{};
      put('#bt-trades', s.trades??0);
      put('#bt-wl', (s.wins??0)+'/'+(s.losses??0));
      put('#bt-winrate', (s.winrate??0).toFixed(2)+'%');
      put('#bt-netpnl', (s.net_pnl??0).toFixed(2));
      put('#bt-mdd', (s.max_drawdown??0).toFixed(2));
      put('#bt-equity', (s.final_equity??0).toFixed(2));
      put('#bt-sharpe', (s.sharpe??0).toFixed(2));
      if(tbody && Array.isArray(d.trades)){
        const f=(ts)=> new Date(ts).toLocaleString();
        for(const t of d.trades){
          const tr=document.createElement('tr');
          [f(t.entry_ts), f(t.exit_ts), t.side||'—',
           t.entry!=null?t.entry.toFixed(2):'—',
           t.exit!=null?t.exit.toFixed(2):'—',
           t.pnl!=null?t.pnl.toFixed(2):'—'
          ].forEach(c=>{ const td=document.createElement('td'); td.textContent=String(c); tr.appendChild(td); });
          tbody.appendChild(tr);
        }
      }
    }catch(e){ alert('Backtest error'); console.error(e); }
  }

  let loopsEnabled=true;
  // Control handles for aborting asynchronous polling loops. Each key
  // corresponds to a different data source. A new key 'health' is added to
  // manage polling of the health endpoint.
  const ctrls={price:null,status:null,logs:null,hist:null,health:null};
  function startLoop(key,fn,ms){
    stopLoop(key);
    const run=async()=>{
      if(!loopsEnabled){ schedule(); return; }
      try{
        const c=new AbortController();
        ctrls[key]=c;
        await fn(c.signal);
      }catch(_){}
      finally{ schedule(); }
    };
    function schedule(){ setTimeout(run,ms); }
    run();
  }
  function stopLoop(key){ try{ ctrls[key]?.abort(); }catch(_){ } ctrls[key]=null; }
  function pauseAll(){ loopsEnabled=false; Object.keys(ctrls).forEach(stopLoop); }
  function resumeAll(){
    loopsEnabled=true;
    startLoop('price', refreshPriceOnce, 3000);
    startLoop('status', refreshStatusOnce, 2000);
    startLoop('logs', refreshLogsOnce, 1500);
    startLoop('hist', refreshHistoryOnce, 5000);
    // poll the health endpoint every 5 seconds
    startLoop('health', refreshHealthOnce, 5000);
  }

  async function runBot(){
    const payload=profileCollect();
    try{
      const r=await fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:jf(payload)});
      const d=await r.json().catch(()=>({}));
      if(!r.ok || d.ok===false){ alert('Start failed: '+(d.error||r.statusText)); return; }
      $('#ui-bot') && ($('#ui-bot').textContent='running');
      setTimeout(()=>refreshLogsOnce(new AbortController().signal),200);
      setTimeout(()=>refreshStatusOnce(new AbortController().signal),200);
    }catch(_){ alert('Start failed'); }
  }
  async function stopBot(){
    try{ await fetch('/stop',{method:'POST'}); $('#ui-bot') && ($('#ui-bot').textContent='stopped'); }catch(_){}
  }
  async function killBot(){
    try{ await fetch('/kill',{method:'POST'}); $('#ui-bot') && ($('#ui-bot').textContent='KILLED'); }catch(_){}
  }

  function wire(){
    const autosave=debounce(()=>{ try{ localStorage.setItem(SKEY, jf(profileCollect())); }catch(_){ } },250);
    document.querySelectorAll('input,select,textarea').forEach(el=>{
      el.addEventListener('input', autosave); el.addEventListener('change', autosave);
    });
    const updW=(id,lab)=>{ const el=$(id); if(!el) return; const f=()=>{ const lb=$(lab); if(lb) lb.textContent=(el.value|0)+'%'; }; el.addEventListener('input',f); f(); };
    updW('#w_sma','#w_sma_val'); updW('#w_ema','#w_ema_val'); updW('#w_rsi','#w_rsi_val'); updW('#w_macd','#w_macd_val');
    $('#strategy')?.addEventListener('change',()=>showParamsFor($('#strategy').value));
    $('#symbol')?.addEventListener('change',()=>{ refreshTV(); refreshPriceOnce(new AbortController().signal).catch(()=>{}); });
    $('#timeframe')?.addEventListener('change',refreshTV);
    $('#btn-run')?.addEventListener('click', runBot);
    $('#btn-stop')?.addEventListener('click', stopBot);
    $('#btn-kill')?.addEventListener('click', killBot);
    $('#btn-hist-refresh')?.addEventListener('click',()=>refreshHistoryOnce(new AbortController().signal));
    $('#btn-hist-download')?.addEventListener('click',(e)=>{ e.preventDefault(); window.open('/api/history.csv','_blank'); });
    $('#btn-hist-clear')?.addEventListener('click',async()=>{ if(!confirm('پاک شود؟')) return; try{ await fetch('/api/history/clear',{method:'POST'}); refreshHistoryOnce(new AbortController().signal); }catch(_){} });
    $('#btn-backtest')?.addEventListener('click', runBacktest);
    document.addEventListener('visibilitychange',()=>{ if(document.hidden) pauseAll(); else resumeAll(); });
  }
  
// ---- Live updates via SSE (optional; keeps polling as fallback) ----
function connectSSE(){
  try{
    if(!('EventSource' in window)) return;
    const es = new EventSource('/stream');
    es.onmessage = (ev)=>{
      try{
        const d = JSON.parse(ev.data);
        if(d.type==='heartbeat' || d.type==='bootstrap'){
          refreshStatusOnce(new AbortController().signal).catch(()=>{});
          refreshHistoryOnce(new AbortController().signal).catch(()=>{});
        }else if(d.type==='history_update'){
          refreshHistoryOnce(new AbortController().signal).catch(()=>{});
        }else if(d.type==='status_update'){
          refreshStatusOnce(new AbortController().signal).catch(()=>{});
        }
      }catch(_){}
    };
    es.onerror = ()=>{ try{ es.close(); }catch(_){}; /* silently fallback to polling */ };
  }catch(_){}
}

async function init(){
    await loadStrategies();
    const p=load(); if(p) profileApply(p); else profileApply(profileCollect());
    wire(); refreshTV();
    try{ await refreshPriceOnce(new AbortController().signal);}catch(_){}
    try{ await refreshStatusOnce(new AbortController().signal);}catch(_){}
    try{ await refreshLogsOnce(new AbortController().signal);}catch(_){}
    try{ await refreshHistoryOnce(new AbortController().signal);}catch(_){}
    resumeAll();
    // Establish Server-Sent Events connection for near real-time updates. This
    // call is placed after the initial polling has begun so that SSE
    // complements rather than replaces the polling loops. If SSE is not
    // supported or fails, polling continues as a fallback.
    connectSSE();
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
