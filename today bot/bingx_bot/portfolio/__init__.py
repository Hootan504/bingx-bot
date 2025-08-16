"""Portfolio module providing allocation strategies.

This package defines classes and helpers for allocating risk across multiple
symbols in a portfolio. Strategies determine weights based on fixed
percentages, volatility targeting and correlation constraints. Additional
allocators can be added by subclassing BaseAllocator.
"""

from .allocator import BaseAllocator, FixedAllocator, VolTargetAllocator

__all__ = [
    'BaseAllocator',
    'FixedAllocator',
    'VolTargetAllocator',
]