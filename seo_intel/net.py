"""
Robustness layer (Q3). One HTTP primitive used by every collector + the AI/Slack
POSTs: retries with exponential backoff + jitter, honours Retry-After, and a
per-host circuit breaker so one flaky source degrades instead of crashing the run.
Zero-dependency (urllib) so the whole system runs anywhere without pip install.
"""
from __future__ import annotations
import ssl
import time
import random
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field

_SSL = ssl.create_default_context()


@dataclass
class Response:
    url: str
    status: int
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    final_url: str = ""
    error: str = ""
    attempts: int = 1


class _NoFollow(urllib.request.HTTPRedirectHandler):
    """Disable auto-follow so the crawler can SEE each 3xx hop."""
    def redirect_request(self, *a, **k):
        return None


class RobustClient:
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, timeout=20, max_retries=4, breaker_threshold=5,
                 breaker_cooldown=120, user_agent="SEO-Intel/1.0 (+local-audit)"):
        self.timeout = timeout
        self.max_retries = max_retries
        self.bt = breaker_threshold
        self.bc = breaker_cooldown
        self.ua = user_agent
        self._breaker: dict[str, tuple[int, float]] = {}   # netloc -> (fails, open_until)
        self._follow = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL))
        self._nofollow = urllib.request.build_opener(_NoFollow, urllib.request.HTTPSHandler(context=_SSL))

    def _netloc(self, url):
        return urllib.parse.urlparse(url).netloc

    def breaker_open(self, url) -> bool:
        st = self._breaker.get(self._netloc(url))
        return bool(st and st[1] and time.time() < st[1])

    def _record(self, nl, ok):
        fails, _ = self._breaker.get(nl, (0, 0.0))
        if ok:
            self._breaker[nl] = (0, 0.0)
        else:
            fails += 1
            self._breaker[nl] = (fails, time.time() + self.bc if fails >= self.bt else 0.0)

    def _backoff(self, attempt, headers):
        ra = headers.get("Retry-After") or headers.get("retry-after")
        if ra:
            try:
                time.sleep(min(float(ra), 10))
                return
            except ValueError:
                pass
        time.sleep(min(0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.3), 8))

    def request(self, url, method="GET", data=None, headers=None, no_redirect=False) -> Response:
        nl = self._netloc(url)
        if self.breaker_open(url):
            return Response(url, 0, error="circuit_open")
        opener = self._nofollow if no_redirect else self._follow
        hdrs = {"User-Agent": self.ua}
        if headers:
            hdrs.update(headers)
        last_err = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
                resp = opener.open(req, timeout=self.timeout)
                status, rh = resp.status, dict(resp.headers)
                body = resp.read(3_000_000)
                if status in self.RETRY_STATUS:
                    last_err = f"status {status}"
                    self._backoff(attempt, rh)
                    continue
                self._record(nl, True)
                return Response(url, status, rh, body, resp.geturl(), attempts=attempt)
            except urllib.error.HTTPError as e:
                status, rh = e.code, dict(e.headers or {})
                try:
                    body = e.read(200_000)
                except Exception:
                    body = b""
                if status in self.RETRY_STATUS:
                    last_err = f"status {status}"
                    self._backoff(attempt, rh)
                    continue
                self._record(nl, True)          # server reachable; 3xx/4xx is a valid answer
                return Response(url, status, rh, body, url, attempts=attempt)
            except Exception as e:              # network / TLS / timeout
                last_err = str(e)
                self._record(nl, False)
                if self.breaker_open(url):
                    return Response(url, 0, error=f"circuit_open:{last_err}", attempts=attempt)
                self._backoff(attempt, {})
        self._record(nl, False)
        return Response(url, 0, error=last_err or "max_retries", attempts=self.max_retries)
