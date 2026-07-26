"""Daily fetch: latest video metadata + subtitle URLs for Investment channels.

Runs on GitHub Actions (non-blocked IP) since VPS is bot-detected.
Writes latest.json committed back to repo; VPS consumes via raw.githubusercontent.com.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHANNELS = json.loads(Path("channels.json").read_text(encoding="utf-8"))
CUTOFF_DAYS = 7
PER_CHANNEL = 5
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


def _pick(entries: list[dict]) -> str | None:
    if not entries:
        return None
    for e in entries:
        if e.get("ext") == "vtt":
            return e.get("url")
    for e in entries:
        if e.get("ext") in ("srv3", "srv1", "ttml", "json3"):
            return e.get("url")
    return entries[0].get("url")


def dump_subs(video_id: str, langs: tuple[str, ...] = ("ko", "en")) -> dict[str, str]:
    import os as _os
    cmd = ["yt-dlp", "--dump-json", "--skip-download", "--no-warnings"]
    cookies = _os.environ.get("YT_COOKIES_FILE", "")
    if cookies and Path(cookies).exists():
        cmd += ["--cookies", cookies]
    cmd.append(f"https://www.youtube.com/watch?v={video_id}")
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        if cp.returncode != 0 or not cp.stdout.strip():
            print(f"  yt-dlp fail rc={cp.returncode}", file=sys.stderr)
            return {}
        info = json.loads(cp.stdout)
    except Exception as e:
        print(f"  exception: {e}", file=sys.stderr)
        return {}
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    out: dict[str, str] = {}
    for lang in langs:
        u = _pick(subs.get(lang) or []) or _pick(auto.get(lang) or [])
        if u:
            out[lang] = u
    return out


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
            urls = dump_subs(v["id"])
            videos[v["id"]] = {
                "channel": name,
                "channel_id": cid,
                "title": v["title"],
                "published": v["published"],
                "subs": urls,
            }
            print(f"[{name}] {v['id']} — subs: {list(urls.keys()) or 'none'} — {v['title'][:60]}")
            time.sleep(1)
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
