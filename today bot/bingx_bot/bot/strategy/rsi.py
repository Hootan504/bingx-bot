from __future__ import annotations
from dataclasses import dataclass
from typing import List
from .utils import rsi
@dataclass
class RSIStrategy:
    period:int=14; oversold:float=30.0; overbought:float=70.0
    def name(self)->str: return "rsi"
    def description(self)->str: return f"RSI strategy with period={self.period}, oversold={self.oversold}, overbought={self.overbought}."
    def compute_signal(self, closes_tf:List[float], closes_trend:List[float])->str:
        val=rsi(closes_tf,self.period)
        if val is None: return "flat"
        if val<self.oversold: return "long"
        if val>self.overbought: return "short"
        return "flat"
