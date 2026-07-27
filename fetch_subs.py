"""Daily fetch: latest video metadata + subtitle URLs + full transcript for Investment channels.

Primary: CF Worker (yt-subs-worker) — returns signed timedtext URLs (ip=0.0.0.0, 24h).
Fallback: youtube-transcript-api on GHA runner — stores full text in cache when worker misses.
VPS fetcher reads `subs` (signed URLs) first, then `transcript` (text) as backup.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHANNELS = json.loads(Path("channels.json").read_text(encoding="utf-8"))
CUTOFF_DAYS = 7
PER_CHANNEL = 5
WORKER_URL = os.environ.get(
    "YT_SUBS_WORKER_URL",
    "https://yt-subs-worker.martinkim3147.workers.dev/subs",
)
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}


def latest_video_ids(channel_id: str, days: int) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for entry in root.findall("a:entry", NS)[:PER_CHANNEL]:
        vid_el = entry.find("yt:videoId", NS)
        title_el = entry.find("a:title", NS)
        pub_el = entry.find("a:published", NS)
        if vid_el is None:
            continue
        pub = pub_el.text if (pub_el is not None and pub_el.text) else ""
        try:
            pdt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            pdt = None
        if pdt and pdt < cutoff:
            continue
        out.append({
            "id": vid_el.text,
            "title": (title_el.text if title_el is not None else "") or "",
            "published": pub,
        })
    return out


def fetch_subs_via_worker(video_id: str, retries: int = 3) -> dict[str, str]:
    """CF Worker returns {"subs": {"ko": "https://...", "en": "..."}}."""
    last_err = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{WORKER_URL}?vid={video_id}&langs=ko,en",
                headers={"User-Agent": "investment-yt-cache/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data.get("subs", {}) or {}
        except Exception as e:
            last_err = str(e)[:100]
            time.sleep(1 + attempt)
    print(f"  worker fail after {retries}: {last_err}", file=sys.stderr)
    return {}


def fetch_transcript_direct(video_id: str, char_cap: int = 6000) -> str:
    """youtube-transcript-api on GHA runner. Fallback when CF Worker signed URLs miss.

    GHA IPs pool is decent; blocked minority filtered by RequestBlocked. Auto/manual
    captions both accepted, ko preferred.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return ""
    api = YouTubeTranscriptApi()
    for langs in (["ko"], ["en"], ["ko", "en"]):
        try:
            segs = api.fetch(video_id, languages=langs)
            text = " ".join(s.text for s in segs).strip()
            if text:
                return text[:char_cap]
        except Exception:
            continue
    return ""


def main() -> None:
    videos: dict[str, dict] = {}
    for ch in CHANNELS:
        cid, name = ch["id"], ch["name"]
        try:
            entries = latest_video_ids(cid, CUTOFF_DAYS)
        except Exception as e:
            print(f"[{name}] RSS fail: {e}", file=sys.stderr)
            continue
        for v in entries:
            urls = fetch_subs_via_worker(v["id"])
            transcript = ""
            if not urls:
                transcript = fetch_transcript_direct(v["id"])
            videos[v["id"]] = {
                "channel": name,
                "channel_id": cid,
                "title": v["title"],
                "published": v["published"],
                "subs": urls,
                "transcript": transcript,
            }
            src = list(urls.keys()) if urls else (["transcript"] if transcript else "none")
            print(f"[{name}] {v['id']} — {src} — {v['title'][:60]}")
            time.sleep(0.5)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(videos),
        "videos": videos,
    }
    Path("latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nWrote latest.json — {len(videos)} videos across {len(CHANNELS)} channels.")


if __name__ == "__main__":
    main()
