from __future__ import annotations
from typing import List, Optional, Tuple
def sma(v:List[float], p:int)->Optional[float]:
    if len(v)<p or p<=0: return None
    return sum(v[-p:])/float(p)
def ema(v:List[float], p:int)->Optional[float]:
    if len(v)<p or p<=0: return None
    k=2.0/(p+1); e=sum(v[:p])/float(p)
    for x in v[p:]: e=x*k+e*(1-k)
    return e
def rsi(v:List[float], p:int=14)->Optional[float]:
    if len(v)<p+1 or p<=0: return None
    g=l=0.0
    for i in range(-p,0):
        d=v[i]-v[i-1]
        if d>0: g+=d
        else: l-=d
    if l==0: return 100.0
    if g==0: return 0.0
    rs=g/l; return 100.0-(100.0/(1.0+rs))
def macd(v:List[float], f:int=12, s:int=26, sig:int=9)->Optional[Tuple[float,float,float]]:
    if len(v)<max(f,s,sig)+1: return None
    from .utils import ema as _ema
    ml=[]
    for i in range(s, len(v)):
        ef=_ema(v[:i+1], f); es=_ema(v[:i+1], s)
        if ef is not None and es is not None: ml.append(ef-es)
    if len(ml)<sig: return None
    macd_val=ml[-1]; signal=_ema(ml, sig)
    if signal is None: return None
    return macd_val, signal, macd_val-signal
