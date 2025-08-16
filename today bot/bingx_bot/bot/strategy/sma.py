from __future__ import annotations
from dataclasses import dataclass
from typing import List
from .utils import sma
@dataclass
class SMACrossoverStrategy:
    tf_fast:int=10; tf_slow:int=20; trend_fast:int=50; trend_slow:int=200
    def name(self)->str: return "sma"
    def description(self)->str: return f"SMA crossover strategy using TF ({self.tf_fast}/{self.tf_slow}) and trend filter ({self.trend_fast}/{self.trend_slow})."
    def compute_signal(self, closes_tf:List[float], closes_trend:List[float])->str:
        t1=sma(closes_trend,self.trend_fast); t2=sma(closes_trend,self.trend_slow)
        if t1 is None or t2 is None: return "flat"
        bias=1 if t1>t2 else -1
        f=sma(closes_tf,self.tf_fast); s=sma(closes_tf,self.tf_slow)
        if f is None or s is None: return "flat"
        if bias>0 and f>s: return "long"
        if bias<0 and f<s: return "short"
        return "flat"
