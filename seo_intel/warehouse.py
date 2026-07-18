"""
Storage layer. SQLite stands in for PostgreSQL (same table shape). Holds pages,
issues, job_runs (observability), ai_cache (cost control), and dead_letter
(rejected data + rejected AI output). This IS "log everything into the data stack".
"""
from __future__ import annotations
import json
import sqlite3
import time
from datetime import datetime, timezone


class Warehouse:
    def __init__(self, db_path):
        self.con = sqlite3.connect(str(db_path))
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS pages(
                run_id INT, url TEXT, depth INT, status INT, final_url TEXT,
                title TEXT, meta_robots TEXT, canonical TEXT, word_count INT,
                content_hash TEXT, content_type TEXT);
            CREATE TABLE IF NOT EXISTS issues(
                run_id INT, priority REAL, band TEXT, check_key TEXT,
                url TEXT, severity REAL, importance REAL, detail TEXT);
            CREATE INDEX IF NOT EXISTS ix_issues ON issues(run_id, priority DESC);
            CREATE TABLE IF NOT EXISTS job_runs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, target TEXT, status TEXT,
                started_at TEXT, finished_at TEXT, duration_s REAL, pages INT, issues INT,
                tokens_in INT, tokens_out INT, cost_usd REAL, ai_mode TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS ai_cache(
                task TEXT, content_hash TEXT, prompt_version TEXT, result TEXT,
                tokens_in INT, tokens_out INT, cost_usd REAL, created_at TEXT,
                PRIMARY KEY(task, content_hash, prompt_version));
            CREATE TABLE IF NOT EXISTS dead_letter(
                created_at TEXT, kind TEXT, ref TEXT, reason TEXT, payload TEXT);
        """)
        self.con.commit()

    def _now(self):
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # ---- observability: job_runs ----
    def start_job(self, job, target):
        cur = self.con.execute(
            "INSERT INTO job_runs(job,target,status,started_at) VALUES(?,?,?,?)",
            (job, target, "running", self._now()))
        self.con.commit()
        self._t0 = time.time()
        return cur.lastrowid

    def finish_job(self, run_id, status, pages=0, issues=0, tokens_in=0, tokens_out=0,
                   cost=0.0, ai_mode="mock", error=""):
        self.con.execute(
            """UPDATE job_runs SET status=?, finished_at=?, duration_s=?, pages=?, issues=?,
               tokens_in=?, tokens_out=?, cost_usd=?, ai_mode=?, error=? WHERE id=?""",
            (status, self._now(), round(time.time() - getattr(self, "_t0", time.time()), 2),
             pages, issues, tokens_in, tokens_out, round(cost, 4), ai_mode, error, run_id))
        self.con.commit()

    # ---- core data ----
    def persist(self, run_id, pages, scored):
        self.con.executemany(
            "INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, p.url, p.depth, p.status, p.final_url, p.title, p.meta_robots,
              p.canonical, p.word_count, p.content_hash, p.content_type) for p in pages.values()])
        self.con.executemany(
            "INSERT INTO issues VALUES(?,?,?,?,?,?,?,?)",
            [(run_id, s.priority, s.band, s.issue.check, s.issue.url, s.issue.severity,
              s.importance, s.issue.detail) for s in scored])
        self.con.commit()

    # ---- ai cache ----
    def ai_cache_get(self, task, h, ver):
        row = self.con.execute(
            "SELECT result FROM ai_cache WHERE task=? AND content_hash=? AND prompt_version=?",
            (task, h, ver)).fetchone()
        return json.loads(row[0]) if row else None

    def ai_cache_set(self, task, h, ver, result, ti, to, cost):
        self.con.execute(
            "INSERT OR REPLACE INTO ai_cache VALUES(?,?,?,?,?,?,?,?)",
            (task, h, ver, json.dumps(result), ti, to, round(cost, 4), self._now()))
        self.con.commit()

    # ---- dead letter ----
    def dead_letter(self, rejects):
        self.con.executemany(
            "INSERT INTO dead_letter VALUES(?,?,?,?,?)",
            [(self._now(), "data", url, reason, "") for url, reason, _ in rejects])
        self.con.commit()

    def dead_letter_ai(self, task, payload, reason):
        self.con.execute("INSERT INTO dead_letter VALUES(?,?,?,?,?)",
                         (self._now(), "ai_output", task, reason, json.dumps(payload)[:2000]))
        self.con.commit()

    def close(self):
        self.con.close()
