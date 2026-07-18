"""Normalize layer. Typed records. (dataclasses here; pydantic in production.)"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Page:
    url: str
    depth: int
    status: int = 0
    final_url: str = ""
    content_type: str = ""
    title: str | None = None
    meta_robots: str | None = None
    x_robots: str | None = None
    description: str | None = None
    canonical: str | None = None
    lang: str | None = None
    has_viewport: bool = False
    h1s: list = field(default_factory=list)
    word_count: int = 0
    img_total: int = 0
    img_no_alt: int = 0
    content_hash: str = ""
    redirect_chain: list = field(default_factory=list)
    links_internal: list = field(default_factory=list)
    error: str = ""


@dataclass
class Issue:
    check: str
    url: str
    severity: float
    detail: str


@dataclass
class ScoredIssue:
    priority: float
    band: str          # P0 | P1 | P2 | LOG
    issue: Issue
    importance: float
