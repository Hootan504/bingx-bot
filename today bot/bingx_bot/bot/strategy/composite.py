from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Any
@dataclass
class CompositeStrategy:
    strategies: List[Any] = field(default_factory=list)
    def name(self)->str: return "composite(" + ",".join(getattr(s,"name")() for s in self.strategies) + ")"
    def description(self)->str: return "Composite of: " + ", ".join(getattr(s,"description")() for s in self.strategies)
    def compute_signal(self, closes_tf:List[float], closes_trend:List[float])->str:
        long_v=short_v=0
        for s in self.strategies:
            try: g=s.compute_signal(closes_tf, closes_trend)
            except Exception: g="flat"
            if g=="long": long_v+=1
            elif g=="short": short_v+=1
        if long_v>short_v and long_v>0: return "long"
        if short_v>long_v and short_v>0: return "short"
        return "flat"
