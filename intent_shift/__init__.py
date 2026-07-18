"""
Part 3 — Automated Ranking-Drop Diagnosis (Intent-Shift Detection & beyond).

A landing page drops Position 2 -> 9 for a high-value keyword. This module decides
*why*, then alerts. It reuses the Part 2 platform's robustness (seo_intel.net) and
config (seo_intel.config), and applies the same principle: deterministic checks
resolve what they can (technical decay, cannibalization, AI-Overview intrusion,
SERP-feature expansion, volatility) and the LLM is used ONLY for the genuine
judgment call — intent shift vs content decay.
"""
__version__ = "1.0.0"
