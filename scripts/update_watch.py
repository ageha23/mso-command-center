#!/usr/bin/env python3
"""
Daily Ethics Watch updater.

Searches CourtListener (case law) and Google News RSS (articles/guidance)
for new items on law firm MSOs, nonlawyer ownership, Rule 5.4, ABS licensing,
and fee-splitting, and merges any new, not-already-seen items into
data/ethics-watch.json.

Runs headless in GitHub Actions on a daily cron (see
.github/workflows/daily-update.yml). No API key required for either source.

Design notes:
- Dedup key is the item's canonical URL.
- We keep at most MAX_ITEMS, dropping the oldest by "date" once over the cap,
  so the JSON file (and the page) stay small.
- Any single source failing (timeout, schema change, rate limit) must not
  crash the whole run - each source is wrapped in its own try/except and the
  script always writes back a valid JSON file with a lastRunStatus note.
"""
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "ethics-watch.json"

MAX_ITEMS = 150
LOOKBACK_DAYS = 4  # overlap window so a missed/late run doesn't lose items
USER_AGENT = "Mozilla/5.0 (compatible; PolsinelliMSOWatch/1.0; +https://github.com/)"
TIMEOUT = 25

# Keyword set scoped to MSO / nonlawyer-ownership legal ethics only.
KEYWORDS = [
    "law firm MSO",
    "nonlawyer ownership law firm",
    "Rule 5.4 ethics opinion",
    "alternative business structure law firm",
    "management services organization law firm",
    "fee splitting law firm ethics",
    "corporate practice of law doctrine",
    "law firm private equity ownership ethics",
]


def http_get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:400]


def load_existing():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text())
        except Exception:
            pass
    return {"lastRun": None, "lastRunStatus": "not run yet", "items": []}


def fetch_courtlistener(cutoff_date):
    """Search CourtListener v4 opinions API for recent MSO/ethics case law."""
    items = []
    query = " OR ".join('"%s"' % kw for kw in [
        "management services organization",
        "nonlawyer ownership",
        "Rule 5.4",
        "fee splitting attorney",
        "corporate practice of law",
    ])
    params = {
        "q": query,
        "type": "o",
        "order_by": "dateFiled desc",
        "filed_after": cutoff_date.strftime("%Y-%m-%d"),
    }
    url = "https://www.courtlistener.com/api/rest/v4/search/?" + urllib.parse.urlencode(params)
    raw = http_get(url)
    data = json.loads(raw)
    for r in data.get("results", [])[:25]:
        case_url = "https://www.courtlistener.com" + r.get("absolute_url", "")
        title = r.get("caseName") or r.get("case_name") or "Untitled opinion"
        date_filed = r.get("dateFiled") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        court = r.get("court") or r.get("court_id") or "Court not specified"
        snippet = strip_html(r.get("snippet") or "")
        items.append({
            "id": "cl:" + case_url,
            "type": "case",
            "title": title,
            "date": date_filed,
            "source": court,
            "url": case_url,
            "snippet": snippet or "New opinion matching MSO / nonlawyer-ownership / Rule 5.4 search terms.",
        })
    return items


def fetch_news_rss(cutoff_date):
    """Google News RSS search, one request per keyword, filtered to recent items."""
    items = []
    for kw in KEYWORDS:
        q = urllib.parse.quote(f'{kw} when:{LOOKBACK_DAYS}d')
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        try:
            raw = http_get(url)
        except Exception as e:
            print(f"  [news] skip '{kw}': {e}", file=sys.stderr)
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"  [news] parse error '{kw}': {e}", file=sys.stderr)
            continue
        for item in root.findall(".//item")[:8]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date_raw = item.findtext("pubDate")
            source_el = item.find("source")
            source = source_el.text if source_el is not None else "News"
            desc = strip_html(item.findtext("description") or "")
            if not title or not link:
                continue
            try:
                pub_dt = datetime.strptime(pub_date_raw, "%a, %d %b %Y %H:%M:%S %Z")
            except Exception:
                pub_dt = datetime.now(timezone.utc)
            items.append({
                "id": "news:" + link,
                "type": "article",
                "title": title,
                "date": pub_dt.strftime("%Y-%m-%d"),
                "source": source,
                "url": link,
                "snippet": desc,
            })
    return items


def main():
    existing = load_existing()
    existing_items = existing.get("items", [])
    seen_urls = {it["url"] for it in existing_items if "url" in it}

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    new_items = []
    errors = []

    try:
        cl_items = fetch_courtlistener(cutoff)
        new_items.extend(cl_items)
        print(f"CourtListener: {len(cl_items)} results")
    except Exception as e:
        errors.append(f"courtlistener: {e}")
        print(f"CourtListener fetch failed: {e}", file=sys.stderr)

    try:
        news_items = fetch_news_rss(cutoff)
        new_items.extend(news_items)
        print(f"News RSS: {len(news_items)} results")
    except Exception as e:
        errors.append(f"news_rss: {e}")
        print(f"News RSS fetch failed: {e}", file=sys.stderr)

    added = 0
    for it in new_items:
        if it["url"] in seen_urls:
            continue
        seen_urls.add(it["url"])
        existing_items.append(it)
        added += 1

    # Keep the file bounded: newest MAX_ITEMS by date.
    existing_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    trimmed = existing_items[:MAX_ITEMS]

    status = "ok" if not errors else ("partial: " + "; ".join(errors))
    out = {
        "lastRun": datetime.now(timezone.utc).isoformat(),
        "lastRunStatus": status,
        "addedThisRun": added,
        "items": trimmed,
    }
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {len(trimmed)} items ({added} new this run). Status: {status}")


if __name__ == "__main__":
    main()
