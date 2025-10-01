"""
Helper modules for the cost-of-solar-storage analysis pipeline.

This package contains utility functions and helper classes used throughout
the analysis pipeline for home electrification cost modeling.

Available modules:
- utility_helpers: Utility company mappings and functions
- gas_rate_helpers: Gas rate structures and calculations  
- electricity_rate_helpers: Electricity rate structures and calculations
- maps_helpers: Geographic mapping and visualization utilities
- capital_costs_helper: Capital cost calculations and incentive handling
- payback_period_helper: Payback period analysis functions
- custom_dispatch_logging: Logging helpers for custom battery dispatch
"""

from .custom_dispatch_logging import log_profiles, summarize_series
