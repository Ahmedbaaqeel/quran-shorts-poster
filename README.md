# quran-shorts poster

Posts one Quran recitation video a day to Instagram (Reels) and TikTok, through Buffer. It runs on GitHub Actions, so the owner's PC can be off.

## How it works

1. `schedule.json` lists each video's posting date, caption and file name. The video files are assets of the `videos` release.
2. Every day at 13:00 and 14:00 UTC (16:00 and 17:00 Riyadh), the **Daily post** workflow:
   - puts yesterday's, today's and tomorrow's videos on this repo's GitHub Pages site (Buffer needs a direct public link),
   - asks Buffer to publish today's video at `post_time` from `config.json` (18:00 Riyadh) on the connected Instagram and TikTok channels,
   - writes what it queued to `posted.json` and commits it.
   The second run only fills in whatever the first one missed, so nothing posts twice.
3. If anything fails, GitHub emails the repo owner and the run shows a red mark under **Actions**. Warnings (for example "only 7 videos left") show as yellow notes on the run.

The schedule and videos are sent from the PC with `python src/poster_sync.py sync` in the quran-shorts project.

## Settings (`config.json`)

- `post_time`, `timezone`: when the posts go out.
- `platforms`: `instagram`, `tiktok`, or both.
- `thumbnail_offset_ms`: which frame Buffer uses as the cover.

Change these in the quran-shorts project's `poster/config.json` and run `poster_sync.py sync`, or edit the file here on GitHub (from a phone too). If you change `post_time` by more than an hour or so, also change the two `cron` lines in `.github/workflows/post.yml` so they run 1 to 2 hours before it (cron is in UTC).

## Run by hand

**Actions → Daily post → Run workflow**. Tick "Dry run" to check the setup without sending anything.

## Secret

`BUFFER_API_KEY`: a Buffer API key from https://publish.buffer.com/settings/api, saved under **Settings → Secrets and variables → Actions**.
