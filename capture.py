"""Daily capture of public rental listing pages in Kingston, Ontario.

For each source in sources.json, fetch the public page(s) once in a headless
browser (so script-loaded listings render), save the rendered HTML under
out/pages/<source>/, and write out/status.json (HTTP status, size, hash).
The workflow publishes out/ as the only commit on the "latest" branch,
replacing the previous day's.
Waits a few seconds between requests to the same host.

Usage: python capture.py [--only source1,source2]
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

UA = "rental-market-runner/1.0 (+https://github.com/market-kingston/rental-market-runner)"
HOST_DELAY = 3.0          # seconds between requests to the same host
NAV_TIMEOUT = 45_000      # ms
ROOT = Path(__file__).resolve().parent
TODAY = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d")

_last_hit = {}


def slug(url):
    p = urlparse(url)
    s = re.sub(r"[^A-Za-z0-9]+", "-", (p.netloc + p.path + ("?" + p.query if p.query else ""))).strip("-")
    return s[:150] or "index"


def wait_for_host(url):
    host = urlparse(url).netloc
    gap = time.time() - _last_hit.get(host, 0)
    if gap < HOST_DELAY:
        time.sleep(HOST_DELAY - gap)
    _last_hit[host] = time.time()


def fetch(page, url, outdir, as_json=False):
    rec = {"url": url, "ok": False}
    wait_for_host(url)
    try:
        if as_json:
            resp = page.request.get(url, headers={"User-Agent": UA}, timeout=NAV_TIMEOUT)
            body = resp.text()
            rec["status"] = resp.status
        else:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:
                pass  # some sites never go idle; keep what has rendered
            body = page.content()
            rec["status"] = resp.status if resp else None
            rec["final_url"] = page.url
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        return rec, None
    name = slug(url) + (".json" if as_json else ".html")
    (outdir / name).write_text(body, encoding="utf-8")
    rec.update(ok=bool(rec.get("status")) and rec["status"] < 400, file=name,
               bytes=len(body.encode()), sha256=hashlib.sha256(body.encode()).hexdigest())
    return rec, body


def links(page, pattern):
    try:
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
    except Exception:
        return []
    rx = re.compile(pattern)
    seen, out = set(), []
    for h in hrefs:
        h = h.split("#")[0]
        if h and rx.search(h) and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def capture_source(page, name, cfg, outroot):
    outdir = outroot / name
    outdir.mkdir(parents=True, exist_ok=True)
    recs = []
    kind = cfg["kind"]
    if kind == "json_repeat":
        ids_seen, quiet = set(), 0
        for i in range(cfg.get("max_repeats", 10)):
            rec, body = fetch(page, cfg["url"] + f"&_r={i}", outdir, as_json=True)
            recs.append(rec)
            new = set()
            try:
                new = {str(u.get("id")) for u in find_units(json.loads(body or "null")) if u.get("listed")}
            except Exception:
                pass
            quiet = quiet + 1 if not (new - ids_seen) else 0
            ids_seen |= new
            if quiet >= 2:
                break
        for url in cfg.get("extra", []):
            recs.append(fetch(page, url, outdir, as_json=True)[0])
    elif kind == "paged":
        for n in range(1, cfg.get("max_pages", 20) + 1):
            rec, body = fetch(page, cfg["url"].format(n=n), outdir)
            recs.append(rec)
            if not body or cfg["until_missing"] not in body:
                break
    else:
        queue = list(cfg["urls"])
        done = set()
        followed = 0
        while queue:
            url = queue.pop(0)
            if url in done:
                continue
            done.add(url)
            rec, body = fetch(page, url, outdir)
            recs.append(rec)
            if body and cfg.get("follow") and url in cfg["urls"]:
                for h in links(page, cfg["follow"]):
                    if h not in done and followed < cfg.get("max_follow", 10):
                        queue.append(h)
                        followed += 1
    return {"source": name, "pages": recs,
            "ok": sum(r.get("ok", False) for r in recs), "failed": sum(not r.get("ok", False) for r in recs)}


def find_units(obj):
    """Return the first list of dicts that carry an 'id' (feed shape varies)."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "id" in obj[0]:
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            r = find_units(v)
            if r:
                return r
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    sources = json.loads((ROOT / "sources.json").read_text())
    only = {s for s in args.only.split(",") if s}
    out = ROOT / "out"
    status = {"date": TODAY, "sources": {}}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        for name, cfg in sources.items():
            if only and name not in only:
                continue
            try:
                status["sources"][name] = capture_source(page, name, cfg, out / "pages")
            except Exception as e:
                status["sources"][name] = {"source": name, "error": f"{type(e).__name__}: {e}"[:400]}
            s = status["sources"][name]
            print(f"{name:14s} ok={s.get('ok')} failed={s.get('failed')} {s.get('error', '')}", flush=True)
        browser.close()
    (out / "status.json").write_text(json.dumps(status, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
