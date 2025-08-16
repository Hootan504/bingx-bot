from __future__ import annotations
from dataclasses import dataclass
from typing import List
from .utils import macd
@dataclass
class MACDStrategy:
    fast:int=12; slow:int=26; signal:int=9
    def name(self)->str: return "macd"
    def description(self)->str: return f"MACD strategy with fast={self.fast}, slow={self.slow}, signal={self.signal}. Produces long when histogram > 0, short when histogram < 0."
    def compute_signal(self, closes_tf:List[float], closes_trend:List[float])->str:
        r=macd(closes_tf,self.fast,self.slow,self.signal)
        if r is None: return "flat"
        macd_val,signal,hist=r
        if hist>0: return "long"
        if hist<0: return "short"
        return "flat"
