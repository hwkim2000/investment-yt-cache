# investment-yt-cache

Daily-refreshed cache of YouTube subtitle URLs for Investment daily brief.

**Why:** VPS (`146.56.108.100`) is bot-detected by YouTube — yt-dlp / youtube-transcript-api / pytubefix all fail. GitHub Actions runs on non-blocked IPs, so we fetch signed timedtext URLs here (24h valid, `ip=0.0.0.0` → any IP can consume) and commit to `latest.json`. VPS pulls raw content and curls each URL directly.

**Schedule:** daily 06:50 KST (`50 21 * * *` UTC).

**Consumer:** VPS `investment-research/tools/fetchers/yt.py` — checks cache first, falls back to local yt-dlp only if cache miss.

## Files

- `channels.json` — channel slate (10 KR + US)
- `fetch_subs.py` — yt-dlp `--dump-json` per video, extracts subtitle URLs
- `.github/workflows/fetch-subs.yml` — cron + commit
- `latest.json` — output (auto-generated, do not edit)

## Manual trigger

```bash
gh workflow run fetch-subs.yml
```
