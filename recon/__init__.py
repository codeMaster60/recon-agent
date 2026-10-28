"""recon-agent: AI-assisted payment reconciliation for small Razorpay merchants.

Pipeline:
    load any file  ->  map columns (LLM, checked by code)  ->  match deterministically
    ->  run exception rules  ->  plain-language report

The LLM is only used where rules break down (messy, bank-specific file layouts and
the written summary). Every number in the output comes from deterministic code.
"""

from .engine import Config, reconcile
from .ingest import load_bank, load_orders, load_report

__all__ = ["Config", "reconcile", "load_bank", "load_orders", "load_report"]
__version__ = "0.1.0"
