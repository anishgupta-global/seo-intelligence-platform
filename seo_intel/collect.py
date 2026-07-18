"""
Collect layer. Async-shaped crawler (redirect-aware, header-aware) + sitemap
seeding. In production this is where GSC / GA4 / DataForSEO collectors also live;
serp.py-style collectors plug in behind the same RobustClient.
"""
from __future__ import annotations
import re
import time
import hashlib
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque

from .models import Page
from .net import RobustClient


def normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = "" if p.path in ("", "/") else p.path.rstrip("/")
    q = f"?{p.query}" if p.query else ""
    return f"{p.scheme}://{p.netloc}{path}{q}"


def same_site(url: str, root_netloc: str) -> bool:
    net = urlparse(url).netloc.lower()
    return net == root_netloc or net.endswith("." + root_netloc.split(":")[0])


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self.meta_robots = None
        self.description = None
        self.canonical = None
        self.lang = None
        self.has_viewport = False
        self.h1s, self._in_h1, self._h1 = [], False, []
        self._raw_hrefs = []
        self.img_total = self.img_no_alt = 0
        self._skip = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            n = (a.get("name") or "").lower()
            if n == "robots":
                self.meta_robots = (a.get("content") or "").lower()
            elif n == "description":
                self.description = a.get("content") or ""
            elif n == "viewport":
                self.has_viewport = True
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        elif tag == "a" and a.get("href"):
            self._raw_hrefs.append(a["href"])
        elif tag == "h1":
            self._in_h1, self._h1 = True, []
        elif tag == "img":
            self.img_total += 1
            if not (a.get("alt") or "").strip():
                self.img_no_alt += 1
        elif tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
            self.h1s.append(" ".join("".join(self._h1).split()))
        elif tag in ("script", "style"):
            self._skip = False

    def handle_data(self, data):
        if self._in_title:
            self.title = ((self.title or "") + data).strip()
        if self._in_h1:
            self._h1.append(data)
        if not self._skip and data.strip():
            self._text.append(data)


def _decode(resp) -> str:
    ctype = (resp.headers.get("Content-Type") or resp.headers.get("content-type") or "").lower()
    if "html" not in ctype:
        return ""
    enc = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        enc = m.group(1)
    try:
        return resp.body.decode(enc, errors="replace")
    except LookupError:
        return resp.body.decode("utf-8", errors="replace")


def _fetch_page(client: RobustClient, url: str):
    """Follow up to 5 redirects manually so each 3xx hop is recorded."""
    chain, current = [], url
    resp = None
    for _ in range(6):
        resp = client.request(current, no_redirect=True)
        if resp.status in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location") or resp.headers.get("location")
            if not loc:
                break
            nxt = urljoin(current, loc)
            chain.append((current, resp.status, nxt))
            current = nxt
            continue
        break
    return resp, chain, current


def load_sitemap_urls(client: RobustClient, start_url: str):
    p = urlparse(start_url)
    base = f"{p.scheme}://{p.netloc}"
    r = client.request(base + "/robots.txt")
    robots_txt = r.body.decode("utf-8", "replace") if r.status == 200 else ""
    queue = [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    for line in robots_txt.splitlines():
        if line.lower().startswith("sitemap:"):
            queue.append(line.split(":", 1)[1].strip())
    found, seen = set(), set()
    while queue:
        sm = queue.pop()
        if sm in seen:
            continue
        seen.add(sm)
        rr = client.request(sm)
        if rr.status != 200 or not rr.body.strip():
            continue
        try:
            root = ET.fromstring(rr.body)
        except ET.ParseError:
            continue
        locs = [e.text.strip() for e in root.iter()
                if e.tag.split("}")[-1] == "loc" and e.text]
        if root.tag.split("}")[-1] == "sitemapindex":
            queue.extend(locs)
        else:
            found.update(locs)
    return found, (r.status == 200)


def crawl(client: RobustClient, settings, log=print):
    start_url = settings.start_url
    root_netloc = urlparse(start_url).netloc.lower()
    seen, pages, status_map = set(), {}, {}

    sitemap_urls, robots_present = load_sitemap_urls(client, start_url)
    sitemap_norm = {normalize_url(u) for u in sitemap_urls if same_site(u, root_netloc)}
    log(f"[collect] robots.txt: {'found' if robots_present else 'missing'} · "
        f"sitemap URLs: {len(sitemap_norm)}")

    q = deque([(normalize_url(start_url), 0)])
    seen.add(normalize_url(start_url))
    for u in sitemap_norm:
        if u not in seen:
            seen.add(u)
            q.append((u, 1))

    while q and len(pages) < settings.max_pages:
        url, depth = q.popleft()
        resp, chain, final = _fetch_page(client, url)
        time.sleep(settings.request_delay)
        status_map[normalize_url(url)] = resp.status
        if final:
            status_map[normalize_url(final)] = resp.status

        pg = Page(url=url, depth=depth, status=resp.status, final_url=final,
                  content_type=(resp.headers.get("Content-Type") or resp.headers.get("content-type") or ""),
                  redirect_chain=chain, error=resp.error,
                  x_robots=(resp.headers.get("X-Robots-Tag") or resp.headers.get("x-robots-tag")))

        html = _decode(resp) if not resp.error else ""
        if html:
            p = PageParser()
            try:
                p.feed(html)
            except Exception:
                pass
            pg.title = p.title
            pg.meta_robots = p.meta_robots
            pg.description = p.description
            pg.canonical = urljoin(final or url, p.canonical) if p.canonical else None
            pg.lang = p.lang
            pg.has_viewport = p.has_viewport
            pg.h1s = p.h1s
            pg.word_count = len(" ".join(p._text).split())
            pg.img_total, pg.img_no_alt = p.img_total, p.img_no_alt
            pg.content_hash = hashlib.sha1(
                re.sub(r"\s+", " ", " ".join(p._text)).strip().encode("utf-8", "replace")).hexdigest()
            for href in p._raw_hrefs:
                absu = urljoin(final or url, href)
                if urlparse(absu).scheme not in ("http", "https"):
                    continue
                nu = normalize_url(absu)
                if same_site(absu, root_netloc):
                    pg.links_internal.append(nu)
                    if (nu not in seen and depth + 1 <= settings.max_depth
                            and not re.search(r"\.(png|jpe?g|gif|svg|webp|ico|css|js|pdf|zip|mp4|woff2?)$", nu, re.I)):
                        seen.add(nu)
                        q.append((nu, depth + 1))
        pages[normalize_url(url)] = pg

    # status-check linked-but-uncrawled URLs (broken-link detection)
    linked = {l for pg in pages.values() for l in pg.links_internal}
    for u in list(linked - set(status_map))[:200]:
        r = client.request(u, no_redirect=True)
        status_map[u] = r.status
        time.sleep(settings.request_delay)

    log(f"[collect] crawled {len(pages)} pages")
    return pages, status_map, sitemap_norm
