"""Optional data sources for the economics: patients (Orphanet) and prices (CMS Medicare spending).

Standard library only. Every number they return carries its source, so the economics can tell sourced inputs [S]
from assumptions [A]. See INTEGRATION.md, section "Economics".
"""
from .market import build_market  # noqa: F401
