"""Import RSS headlines into the editorial queue; never auto-publish."""
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

FEED = "https://feeds.bbci.co.uk/persian/rss.xml"
SOURCE = "BBC Persian"
BASE = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
if not BASE.startswith("https://") or not BASE.endswith(".supabase.co"):
    raise RuntimeError("Invalid Supabase URL")

def request(url, method="GET", payload=None, extra=None):
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
    if payload is not None:
        headers.update({"Content-Type": "application/json", "Prefer": "return=representation"})
    headers.update(extra or {})
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)

source = request(BASE + "/rest/v1/news_sources?select=id,enabled&feed_url=eq." + urllib.parse.quote(FEED, safe=""))
if not source or not source[0]["enabled"]:
    print("Source is disabled; no ingestion.")
    raise SystemExit(0)
feed_req = urllib.request.Request(FEED, headers={"User-Agent": "MosayebNews/0.1 (RSS editorial aggregator)"})
with urllib.request.urlopen(feed_req, timeout=20) as response:
    xml = response.read(2_000_000)
root = ET.fromstring(xml)
count = 0
for item in root.findall(".//channel/item")[:20]:
    title = (item.findtext("title") or "").strip()
    link = (item.findtext("link") or "").strip()
    summary = (item.findtext("description") or "").strip()
    parsed = urllib.parse.urlsplit(link)
    if not title or parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("bbc.com"):
        continue
    existing = request(BASE + "/rest/v1/raw_news?select=id&original_url=eq." + urllib.parse.quote(link, safe=""))
    if existing:
        continue
    rows = request(BASE + "/rest/v1/raw_news", "POST", [{"source_id": source[0]["id"], "original_url": link, "title": title[:500], "content": summary[:4000]}])
    if rows:
        request(BASE + "/rest/v1/news_ai_jobs", "POST", [{"raw_news_id": rows[0]["id"], "status": "pending"}])
        count += 1
print("New items queued for editorial review:", count)
