#!/usr/bin/env python3
"""
Multi-source crawler — Reddit + Hacker News + Google News.

- Collects raw posts/articles from the last N days (default 90).
- Searches by BOTH keywords and full phrases (sentences).
- Saves raw results to JSONL (loss-less) and CSV (spreadsheet-friendly).

Only dependency: `requests`. Everything else is Python stdlib.

Free data sources used (no API key required):
  - Reddit      : Arctic Shift API (Pushshift successor), PullPush.io fallback
  - Hacker News : Algolia search API
  - Google News : RSS search feed

Usage:
    python3 crawler.py                 # uses config.json
    python3 crawler.py --config my.json
    python3 crawler.py --days 30 --keywords "tesla,ev" --phrases "battery fire"
"""

import argparse
import csv
import json
import os
import sys
import time
import html
import re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

try:
    import requests
except ImportError:
    sys.exit("`requests` is required.  Install it with:  python3 -m pip install requests")


# --------------------------------------------------------------------------- #
# Common record schema
# --------------------------------------------------------------------------- #
# Every source is normalized into this dict shape so downstream analysis
# (keyword frequency, sentiment, etc.) can treat all sources uniformly.
#
#   source, id, created_utc (ISO8601), title, text, url, author, score,
#   subreddit, query, matched_keywords, matched_phrases
# --------------------------------------------------------------------------- #

USER_AGENT = "multi-source-crawler/1.0 (research; contact: you@example.com)"


def iso(ts_epoch):
    """epoch seconds -> ISO8601 UTC string."""
    return datetime.fromtimestamp(int(ts_epoch), tz=timezone.utc).isoformat()


def http_get(url, params=None, timeout=30, retries=3):
    """GET with basic retry/backoff. Returns requests.Response or None."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                url, params=params, timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code == 200:
                return r
            # 429 / 5xx -> backoff and retry
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * attempt)
                continue
            sys.stderr.write(f"  ! HTTP {r.status_code} for {r.url}\n")
            return None
        except requests.RequestException as e:
            sys.stderr.write(f"  ! request error ({attempt}/{retries}): {e}\n")
            time.sleep(2 * attempt)
    return None


# --------------------------------------------------------------------------- #
# Source: Reddit
# --------------------------------------------------------------------------- #
# Reality check (2026): unauthenticated reddit.com/.json endpoints return 403,
# and the old Pushshift-style archives (PullPush) lag ~1 year behind, so they
# can't cover "the last 90 days". Two paths that DO work:
#
#   A) OAuth (recommended) — register a free "script" app at
#      https://www.reddit.com/prefs/apps , put client_id/client_secret in
#      config.json. Covers ALL of reddit for the last 90 days. No PRAW needed;
#      we hit oauth.reddit.com directly with `requests`.
#
#   B) Arctic Shift (no auth) — free Pushshift successor, but full-text search
#      MUST be scoped to a subreddit (or author). Set "subreddit" in config.
#
# fetch_reddit() picks A if credentials exist, else B if a subreddit is set,
# else it skips with a clear message.
# --------------------------------------------------------------------------- #
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH = "https://oauth.reddit.com"
ARCTIC_POSTS = "https://arctic-shift.photon-reddit.com/api/posts/search"


def reddit_get_token(client_id, client_secret):
    """App-only (client_credentials) OAuth token. Returns token str or None."""
    try:
        r = requests.post(
            REDDIT_TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": USER_AGENT}, timeout=30,
        )
        if r.status_code != 200:
            sys.stderr.write(f"  ! Reddit token HTTP {r.status_code}: {r.text[:200]}\n")
            return None
        return r.json().get("access_token")
    except requests.RequestException as e:
        sys.stderr.write(f"  ! Reddit token error: {e}\n")
        return None


def fetch_reddit(query, after_epoch, before_epoch, limit, token=None,
                 subreddit=None, delay=1.0):
    if token:
        return _fetch_reddit_oauth(query, after_epoch, before_epoch, limit,
                                   token, subreddit, delay)
    if subreddit:
        return _fetch_reddit_arctic(query, after_epoch, before_epoch, limit,
                                    subreddit, delay)
    return []  # no creds and no subreddit -> nothing we can legally fetch


def _fetch_reddit_oauth(query, after_epoch, before_epoch, limit, token,
                        subreddit, delay):
    out, after = [], None
    base = f"{REDDIT_OAUTH}/r/{subreddit}/search" if subreddit else f"{REDDIT_OAUTH}/search"
    headers = {"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}
    while len(out) < limit:
        params = {"q": query, "sort": "new", "limit": 100, "t": "all", "raw_json": 1}
        if subreddit:
            params["restrict_sr"] = 1
        if after:
            params["after"] = after
        try:
            r = requests.get(base, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            sys.stderr.write(f"    ! reddit oauth error: {e}\n")
            break
        if r.status_code != 200:
            sys.stderr.write(f"    ! reddit oauth HTTP {r.status_code}\n")
            break
        d = r.json().get("data", {})
        children = d.get("children", [])
        if not children:
            break
        stop = False
        for c in children:
            p = c.get("data", {})
            cu = int(p.get("created_utc", 0))
            if cu < after_epoch:   # sorted new->old, so we've passed the window
                stop = True
                break
            if cu > before_epoch:
                continue
            out.append(_norm_reddit(p, query))
        after = d.get("after")
        if stop or not after:
            break
        time.sleep(delay)
    return out[:limit]


def _fetch_reddit_arctic(query, after_epoch, before_epoch, limit, subreddit, delay):
    out, cursor = [], after_epoch
    while len(out) < limit:
        params = {
            "subreddit": subreddit, "query": query,
            "after": iso(cursor), "before": iso(before_epoch),
            "limit": min(100, limit - len(out)), "sort": "asc",
        }
        r = http_get(ARCTIC_POSTS, params=params)
        if r is None:
            break
        try:
            data = r.json().get("data") or []
        except ValueError:
            break
        if not data:
            break
        for d in data:
            out.append(_norm_reddit(d, query))
        newest = max(int(d.get("created_utc", cursor)) for d in data)
        if newest <= cursor:
            break
        cursor = newest + 1
        time.sleep(delay)
    return out


def _norm_reddit(d, query):
    return {
        "source": "reddit",
        "id": d.get("id") or d.get("name"),
        "created_utc": iso(d.get("created_utc", 0)) if d.get("created_utc") else "",
        "title": d.get("title", "") or "",
        "text": d.get("selftext", "") or "",
        "url": f"https://reddit.com{d.get('permalink', '')}" if d.get("permalink") else d.get("url", ""),
        "author": d.get("author", ""),
        "score": d.get("score", ""),
        "subreddit": d.get("subreddit", ""),
        "query": query,
    }


# --------------------------------------------------------------------------- #
# Source: Hacker News via Algolia
# --------------------------------------------------------------------------- #
HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"


def fetch_hackernews(query, after_epoch, before_epoch, limit, delay=1.0):
    out, page = [], 0
    while len(out) < limit:
        params = {
            "query": query,
            "tags": "(story,comment)",
            "numericFilters": f"created_at_i>{after_epoch},created_at_i<{before_epoch}",
            "hitsPerPage": 100,
            "page": page,
        }
        r = http_get(HN_SEARCH, params=params)
        if r is None:
            break
        try:
            payload = r.json()
        except ValueError:
            break
        hits = payload.get("hits", [])
        if not hits:
            break
        for h in hits:
            out.append(_norm_hn(h, query))
        page += 1
        if page >= payload.get("nbPages", 0):
            break
        time.sleep(delay)
    return out[:limit]


def _norm_hn(h, query):
    hn_id = h.get("objectID", "")
    return {
        "source": "hackernews",
        "id": hn_id,
        "created_utc": iso(h["created_at_i"]) if h.get("created_at_i") else h.get("created_at", ""),
        "title": h.get("title") or h.get("story_title") or "",
        "text": h.get("story_text") or h.get("comment_text") or "",
        "url": h.get("url") or f"https://news.ycombinator.com/item?id={hn_id}",
        "author": h.get("author", ""),
        "score": h.get("points", ""),
        "subreddit": "",
        "query": query,
    }


# --------------------------------------------------------------------------- #
# Source: Google News RSS
# --------------------------------------------------------------------------- #
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_TAG = re.compile(r"<[^>]+>")


def fetch_googlenews(query, days_back, hl, gl, ceid, delay=1.0):
    # `when:<N>d` restricts the feed to the last N days.
    params = {"q": f"{query} when:{days_back}d", "hl": hl, "gl": gl, "ceid": ceid}
    r = http_get(GOOGLE_NEWS_RSS, params=params)
    if r is None:
        return []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        sys.stderr.write(f"    ! RSS parse error: {e}\n")
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc_raw = item.findtext("description") or ""
        source_el = item.find("source")
        src_name = source_el.text if source_el is not None else ""
        out.append({
            "source": "googlenews",
            "id": link,
            "created_utc": _parse_rss_date(pub),
            "title": html.unescape(title),
            "text": html.unescape(_TAG.sub(" ", desc_raw)).strip(),
            "url": link,
            "author": src_name or "",
            "score": "",
            "subreddit": "",
            "query": query,
        })
    time.sleep(delay)
    return out


def _parse_rss_date(s):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(s, fmt).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return s


# --------------------------------------------------------------------------- #
# Keyword / phrase matching
# --------------------------------------------------------------------------- #
def annotate_matches(rec, keywords, phrases):
    hay = f"{rec.get('title','')} {rec.get('text','')}".lower()
    rec["matched_keywords"] = [k for k in keywords if k.lower() in hay]
    rec["matched_phrases"] = [p for p in phrases if p.lower() in hay]
    return rec


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run(cfg):
    days = cfg["days_back"]
    now = datetime.now(tz=timezone.utc)
    before_epoch = int(now.timestamp())
    after_epoch = int((now - timedelta(days=days)).timestamp())

    keywords = [k for k in cfg.get("keywords", []) if k.strip()]
    phrases = [p for p in cfg.get("phrases", []) if p.strip()]
    queries = keywords + phrases
    if not queries:
        sys.exit("No keywords or phrases configured. Edit config.json.")

    delay = cfg.get("request_delay_sec", 1.0)
    src = cfg.get("sources", {})
    all_records, seen = [], set()

    # Acquire a Reddit OAuth token once (if credentials are configured).
    reddit_token = None
    rcfg = src.get("reddit", {})
    if rcfg.get("enabled") and rcfg.get("client_id") and rcfg.get("client_secret"):
        reddit_token = reddit_get_token(rcfg["client_id"], rcfg["client_secret"])
        if reddit_token:
            print("Reddit: OAuth token acquired (searching all of reddit).")
        else:
            print("Reddit: OAuth failed — falling back to subreddit/Arctic Shift if set.")
    elif rcfg.get("enabled") and not rcfg.get("subreddit"):
        print("Reddit: no credentials and no subreddit set — Reddit will be skipped.\n"
              "        Add client_id/client_secret (https://www.reddit.com/prefs/apps)\n"
              "        or set a \"subreddit\" to use the no-auth Arctic Shift path.")

    def add(rec):
        key = (rec["source"], str(rec.get("id")))
        if key in seen:
            return
        seen.add(key)
        all_records.append(annotate_matches(rec, keywords, phrases))

    print(f"Window: last {days} days  ({iso(after_epoch)} -> {iso(before_epoch)})")
    print(f"Queries ({len(queries)}): {queries}\n")

    for q in queries:
        print(f"Query: {q!r}")

        if rcfg.get("enabled") and (reddit_token or rcfg.get("subreddit")):
            lim = rcfg.get("limit_per_query", 300)
            sub = rcfg.get("subreddit")
            recs = fetch_reddit(q, after_epoch, before_epoch, lim,
                                token=reddit_token, subreddit=sub, delay=delay)
            print(f"  reddit      : {len(recs)}")
            for r in recs:
                add(r)

        if src.get("hackernews", {}).get("enabled"):
            lim = src["hackernews"].get("limit_per_query", 300)
            recs = fetch_hackernews(q, after_epoch, before_epoch, lim, delay)
            print(f"  hackernews  : {len(recs)}")
            for r in recs:
                add(r)

        if src.get("googlenews", {}).get("enabled"):
            g = src["googlenews"]
            recs = fetch_googlenews(q, days, g.get("hl", "en-US"),
                                    g.get("gl", "US"), g.get("ceid", "US:en"), delay)
            print(f"  googlenews  : {len(recs)}")
            for r in recs:
                add(r)
        print()

    return all_records


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
CSV_FIELDS = ["source", "id", "created_utc", "title", "text", "url", "author",
              "score", "subreddit", "query", "matched_keywords", "matched_phrases"]


def save(records, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    jsonl_path = os.path.join(out_dir, f"crawl_{stamp}.jsonl")
    csv_path = os.path.join(out_dir, f"crawl_{stamp}.csv")

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = dict(r)
            row["matched_keywords"] = ", ".join(r.get("matched_keywords", []))
            row["matched_phrases"] = ", ".join(r.get("matched_phrases", []))
            # keep CSV cells sane
            row["text"] = (row.get("text") or "").replace("\n", " ")[:2000]
            w.writerow(row)

    return jsonl_path, csv_path


def main():
    ap = argparse.ArgumentParser(description="Multi-source 90-day crawler (Reddit/HN/Google News).")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--days", type=int, help="override days_back")
    ap.add_argument("--keywords", help="comma-separated, overrides config")
    ap.add_argument("--phrases", help="comma-separated, overrides config")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = args.config if os.path.isabs(args.config) else os.path.join(here, args.config)
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    if args.days:
        cfg["days_back"] = args.days
    if args.keywords is not None:
        cfg["keywords"] = [s.strip() for s in args.keywords.split(",") if s.strip()]
    if args.phrases is not None:
        cfg["phrases"] = [s.strip() for s in args.phrases.split(",") if s.strip()]

    records = run(cfg)

    out_dir = cfg.get("output_dir", "output")
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(here, out_dir)
    jsonl_path, csv_path = save(records, out_dir)

    # quick summary
    by_source = {}
    for r in records:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print("=" * 50)
    print(f"TOTAL unique records: {len(records)}")
    for s, n in sorted(by_source.items()):
        print(f"  {s:12}: {n}")
    print(f"\nSaved:\n  {jsonl_path}\n  {csv_path}")


if __name__ == "__main__":
    main()
