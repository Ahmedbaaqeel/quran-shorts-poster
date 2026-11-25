#!/usr/bin/env python3
"""Daily poster for the quran-shorts videos. Runs on GitHub Actions.

Each run keeps the next config.json "queue_ahead" scheduled videos queued in
Buffer, each for its own posting day (config.json "post_days") at the
configured time. Buffer then publishes them to the connected Instagram and
TikTok channels, so a few missed GitHub runs never stop a post. Nothing here
needs the owner's PC.

Commands:
  python post.py stage --out site      put the videos for yesterday, today,
                                       tomorrow and the queue_ahead window
                                       into site/v/ (the Pages site)
  python post.py queue                 create the Buffer posts for the next
                                       queue_ahead videos not yet queued
  python post.py status                print what is scheduled and what is left

Environment:
  BUFFER_API_KEY   Buffer personal API key (GitHub secret)
  PAGES_URL        base URL of the deployed Pages site, e.g. https://me.github.io/repo/
  DRY_RUN=1        print what would be sent, change nothing
  POST_NOW=1       queue: post the next unposted video right away (in about 10
                   minutes) instead of waiting for its date. It is logged under
                   today's date; run poster_sync.py sync afterwards so the
                   schedule moves the other videos up.
  FILL_MISSING=1   queue: take the most recently posted video and post it right
                   away (about 10 minutes) to every platform in config.json it
                   has not gone to yet, e.g. a newly connected Instagram. The
                   schedule is not touched.
  ACCOUNT=hadith   use the files in hadith/ (Haditho_97) instead of the top level
  BUFFER_API_URL   override the API endpoint (tests only)
  TODAY            override today's date, YYYY-MM-DD (tests only)

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
# ACCOUNT=hadith reads hadith/config.json, hadith/schedule.json and hadith/posted.json
# (the Haditho_97 account). No ACCOUNT = the original quran-shorts files at the top level.
ACCOUNT = os.environ.get("ACCOUNT", "").strip()
DATA = ROOT / ACCOUNT if ACCOUNT else ROOT
CONFIG = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
SCHEDULE = json.loads((DATA / "schedule.json").read_text(encoding="utf-8"))
POSTED_PATH = DATA / "posted.json"
API_URL = os.environ.get("BUFFER_API_URL", "https://api.buffer.com")
DRY_RUN = os.environ.get("DRY_RUN", "") not in ("", "0", "false")
POST_NOW = os.environ.get("POST_NOW", "") not in ("", "0", "false")
FILL_MISSING = os.environ.get("FILL_MISSING", "") not in ("", "0", "false")
TZ = ZoneInfo(CONFIG["timezone"])
SERVICES = {"instagram", "tiktok"}
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # captions are Arabic


def log(msg: str) -> None:
    print(msg, flush=True)


def gh_warning(msg: str) -> None:
    # Shows as a yellow annotation on the GitHub Actions run page.
    print(f"::warning::{msg}", flush=True)


def today() -> date:
    if os.environ.get("TODAY"):
        return date.fromisoformat(os.environ["TODAY"])
    return datetime.now(TZ).date()


def load_posted() -> dict:
    if POSTED_PATH.exists():
        return json.loads(POSTED_PATH.read_text(encoding="utf-8"))
    return {}


def save_posted(posted: dict) -> None:
    POSTED_PATH.write_text(json.dumps(posted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def entries_on(day: date) -> list[dict]:
    return [e for e in SCHEDULE["videos"] if e["date"] == day.isoformat()]


def upcoming(day: date) -> list[dict]:
    """The next queue_ahead scheduled videos from day on (Buffer free plan allows 10 per channel)."""
    ahead = max(1, int(CONFIG.get("queue_ahead", 1)))
    return [e for e in SCHEDULE["videos"] if e["date"] >= day.isoformat()][:ahead]


def next_unposted(posted: dict, day: date) -> dict | None:
    done = {p.get("file") for p in posted.values()}
    return next((e for e in SCHEDULE["videos"] if e["date"] >= day.isoformat() and e["file"] not in done), None)


# ---------------------------------------------------------------- stage

def cmd_stage(args: argparse.Namespace) -> int:
    """Download the release assets for yesterday..tomorrow into <out>/v/."""
    out = Path(args.out) / "v"
    out.mkdir(parents=True, exist_ok=True)
    t = today()
    wanted = [e for d in (-1, 0, 1) for e in entries_on(t + timedelta(days=d))]
    wanted += [e for e in upcoming(t) if e not in wanted]
    nxt = next_unposted(load_posted(), t) if POST_NOW else None
    if nxt and nxt not in wanted:
        wanted.append(nxt)
    if FILL_MISSING:
        files = {p.get("file") for p in load_posted().values()}
        wanted += [e for e in SCHEDULE["videos"] if e["file"] in files and e not in wanted]
    (Path(args.out) / "index.html").write_text("<!doctype html><title>quran-shorts</title><p>Video files for the daily poster.</p>\n", encoding="utf-8")
    (Path(args.out) / ".nojekyll").write_text("", encoding="utf-8")
    if not wanted:
        gh_warning(f"No videos scheduled around {t}. Add more with poster_sync.py on the PC.")
        return 0
    for e in wanted:
        dest = out / e["file"]
        if dest.exists():
            continue
        if args.local_dir:
            shutil.copy(Path(args.local_dir) / e["file"], dest)
        else:
            cmd = ["gh", "release", "download", SCHEDULE["release_tag"], "--pattern", e["file"], "--dir", str(out)]
            log("$ " + " ".join(cmd))
            subprocess.run(cmd, check=True)
        log(f"staged {e['file']} ({dest.stat().st_size} bytes)")
    return 0


# ---------------------------------------------------------------- Buffer API

def gql(query: str, variables: dict | None = None) -> dict:
    key = os.environ.get("BUFFER_API_KEY", "")
    if not key:
        raise SystemExit("BUFFER_API_KEY is not set. Add it under Settings > Secrets and variables > Actions.")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    for attempt in range(4):
        req = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "quran-shorts-poster"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                wait = int(exc.headers.get("Retry-After") or 60)
                log(f"Buffer rate limit, waiting {wait}s")
                time.sleep(min(wait, 300))
                continue
            if exc.code >= 500 and attempt < 3:
                time.sleep(20)
                continue
            raise SystemExit(f"Buffer API HTTP {exc.code}: {exc.read()[:500]!r}")
        if data.get("errors"):
            raise SystemExit(f"Buffer API error: {json.dumps(data['errors'])[:800]}")
        return data["data"]
    raise SystemExit("Buffer API kept failing")


def _norm(name: str) -> str:
    return str(name or "").strip().lstrip("@").lower()


def channel_wanted(svc: str, name: str) -> bool:
    """config.json "channel_names" pins a platform to one Buffer channel by name.
    Without a pin, channels pinned by another account's folder (e.g. hadith/ for
    Haditho_97) are left alone, so the quran posts never go to the hadith account."""
    pinned = CONFIG.get("channel_names", {}).get(svc)
    if pinned:
        return _norm(name) == _norm(pinned)
    taken = set()
    for other in ROOT.glob("*/config.json"):
        if other.parent != DATA:
            taken |= {_norm(n) for n in json.loads(other.read_text(encoding="utf-8")).get("channel_names", {}).values()}
    return _norm(name) not in taken


def find_channels() -> dict[str, dict]:
    """Return {"instagram": channel, "tiktok": channel} from the Buffer account."""
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    found: dict[str, dict] = {}
    for org in orgs:
        chans = gql("query($org: OrganizationId!) { channels(input: {organizationId: $org}) "
                    "{ id name service isDisconnected isLocked isQueuePaused } }", {"org": org["id"]})["channels"]
        for c in chans:
            svc = str(c.get("service", "")).lower()
            if svc in SERVICES and svc in CONFIG["platforms"] and svc not in found and channel_wanted(svc, c.get("name")):
                found[svc] = c
    return found


CREATE_POST = """
mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id dueAt } }
    ... on MutationError { message }
  }
}"""


def create_post(channel: dict, entry: dict, video_url: str, due: datetime) -> str:
    svc = channel["service"].lower()
    metadata = {"instagram": {"type": "reel", "shouldShareToFeed": True}} if svc == "instagram" else {"tiktok": {}}
    if svc == "tiktok" and CONFIG.get("tiktok_label_ai") is not None:
        metadata["tiktok"]["isAiGenerated"] = bool(CONFIG["tiktok_label_ai"])
    video: dict = {"url": video_url}
    if CONFIG.get("thumbnail_offset_ms"):
        video["metadata"] = {"thumbnailOffset": int(CONFIG["thumbnail_offset_ms"])}
    payload = {
        "channelId": channel["id"],
        "text": entry["caption"],
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "needsApproval": False,
        "assets": [{"video": video}],
        "metadata": metadata,
    }
    if DRY_RUN:
        log(f"DRY RUN createPost {svc}: {json.dumps(payload, ensure_ascii=False)[:400]}")
        return "dry-run"
    res = gql(CREATE_POST, {"input": payload})["createPost"]
    if res.get("__typename") != "PostActionSuccess":
        raise RuntimeError(f"{svc}: {res.get('message') or res}")
    return res["post"]["id"]


# ---------------------------------------------------------------- queue

def url_ready(url: str, size: int) -> bool:
    """True when the video is served directly (no redirect) at the full size."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "quran-shorts-poster"})
        with opener.open(req, timeout=30) as r:
            length = int(r.headers.get("Content-Length") or -1)
            return r.status == 200 and (length == size or length == -1)
    except Exception as exc:  # noqa: BLE001 - any failure means "not yet"
        log(f"  not ready yet: {exc}")
        return False


def due_time(day: date) -> datetime:
    hh, mm = (int(x) for x in CONFIG["post_time"].split(":"))
    due = datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
    soonest = datetime.now(timezone.utc) + timedelta(minutes=10)
    return max(due, soonest)


def cmd_queue(args: argparse.Namespace) -> int:
    t = today()
    posted = load_posted()
    # A video already posted on another day (for example by a POST_NOW test) never goes out twice.
    todays = [e for e in upcoming(t) if posted.get(e["date"], {}).get("file", e["file"]) == e["file"]
              and not any(p.get("file") == e["file"] for d, p in posted.items() if d != e["date"])]
    if FILL_MISSING:
        gaps = [d for d in sorted(posted) if any(s not in posted[d] for s in CONFIG["platforms"])]
        if not gaps:
            raise SystemExit("FILL_MISSING: every posted video is already on " + ", ".join(CONFIG["platforms"]))
        d = gaps[-1]
        src = next((e for e in SCHEDULE["videos"] if e["file"] == posted[d]["file"]), None)
        if not src:
            raise SystemExit(f"FILL_MISSING: {posted[d]['file']} is not in schedule.json")
        log(f"FILL_MISSING: posting {src['file']} (logged {d}) to the platforms it is missing")
        todays = [{**src, "date": d}]
    elif POST_NOW:
        nxt = next_unposted(posted, t)
        if posted.get(t.isoformat()):
            raise SystemExit(f"Something was already posted today ({posted[t.isoformat()].get('file')}); not posting another.")
        if not nxt:
            raise SystemExit("POST_NOW: no unposted video left in the schedule.")
        log(f"POST_NOW: posting {nxt['file']} (scheduled {nxt['date']}) now, logged under {t}")
        todays = [{**nxt, "date": t.isoformat()}]
    left = [e for e in SCHEDULE["videos"] if e["date"] >= t.isoformat()]
    if len(left) <= CONFIG.get("warn_when_days_left", 7):
        gh_warning(f"Only {len(left)} videos left in the schedule (last: {left[-1]['date'] if left else 'none'}). "
                   "Render more on the PC and run poster_sync.py.")
    if not todays:
        post_days = [d[:3].lower() for d in CONFIG.get("post_days", [])]
        if post_days and t.strftime("%a").lower() not in post_days:
            log(f"{t} is not a posting day ({', '.join(post_days)}). Nothing to do.")
        else:
            gh_warning(f"Nothing scheduled for {t}.")
        return 0

    pages = os.environ.get("PAGES_URL", "").rstrip("/")
    if not pages and not DRY_RUN:
        raise SystemExit("PAGES_URL is not set")

    channels = {} if DRY_RUN and not os.environ.get("BUFFER_API_KEY") else find_channels()
    if DRY_RUN and not channels:
        channels = {s: {"id": f"dry-{s}", "service": s, "name": s} for s in CONFIG["platforms"]}
    missing = [s for s in CONFIG["platforms"] if s not in channels]
    for s in missing:
        gh_warning(f"No {s} channel is connected in Buffer.")

    failures = []
    for entry in todays:
        url = f"{pages}/v/{entry['file']}"
        record = posted.setdefault(entry["date"], {"file": entry["file"]})
        todo = [s for s, c in channels.items() if s not in record]
        if not todo:
            log(f"{entry['date']}: already queued on {', '.join(sorted(channels))}")
            continue
        if pages:  # also checked on dry runs: it only reads the public link
            for i in range(20):
                if url_ready(url, entry["size"]):
                    break
                time.sleep(15)
            else:
                raise SystemExit(f"Video is not reachable at {url}")
        due = (datetime.now(timezone.utc) + timedelta(minutes=10) if (POST_NOW or FILL_MISSING)
               else due_time(date.fromisoformat(entry["date"])))
        for svc in todo:
            ch = channels[svc]
            for flag in ("isDisconnected", "isLocked", "isQueuePaused"):
                if ch.get(flag):
                    gh_warning(f"Buffer {svc} channel is {flag[2:]}; the post may not go out.")
            try:
                post_id = create_post(ch, entry, url, due)
            except RuntimeError as exc:
                failures.append(str(exc))
                log(f"FAILED {exc}")
                continue
            record[svc] = {"buffer_post_id": post_id, "due": due.isoformat(), "queued_at": datetime.now(timezone.utc).isoformat()}
            log(f"{entry['date']} {svc}: queued {entry['file']} for {due.isoformat()} (post {post_id})")
    if not DRY_RUN:
        save_posted(posted)
    if failures or missing:
        raise SystemExit("Some posts were not queued: " + "; ".join(failures + [f"{s} not connected" for s in missing]))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    t = today()
    posted = load_posted()
    left = [e for e in SCHEDULE["videos"] if e["date"] >= t.isoformat()]
    log(f"today {t}, post time {CONFIG['post_time']} {CONFIG['timezone']}, {len(left)} videos left"
        + (f" (last {left[-1]['date']})" if left else ""))
    for d in sorted(posted)[-7:]:
        log(f"  {d}: {', '.join(k for k in posted[d] if k != 'file') or 'nothing'}  {posted[d].get('file')}")
    return 0


SCHEMA_TYPES = ["CreatePostInput", "AssetInput", "VideoAssetInput", "VideoMetadataInput", "PostInputMetaData",
                "InstagramPostMetadataInput", "TikTokPostMetadataInput", "ShareMode", "SchedulingType", "PostType",
                "PostActionPayload", "MutationError", "PostActionSuccess"]


def cmd_schema(args: argparse.Namespace) -> int:
    """Read-only: print Buffer's schema for the types createPost uses."""
    def tname(t):
        return t["name"] or f"{t['kind']}({tname(t['ofType'])})"
    q = """query($n: String!) { __type(name: $n) { kind name
      inputFields { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }
      fields { name } enumValues { name } possibleTypes { name } } }"""
    for n in SCHEMA_TYPES:
        ty = gql(q, {"n": n})["__type"]
        if not ty:
            log(f"{n}: MISSING")
            continue
        parts = [f"{f['name']}:{tname(f['type'])}" for f in ty.get("inputFields") or []]
        parts += [f["name"] for f in ty.get("fields") or []][:12]
        parts += [e["name"] for e in ty.get("enumValues") or []]
        parts += ["|" + p["name"] for p in ty.get("possibleTypes") or []]
        log(f"{n} ({ty['kind']}): " + ", ".join(parts))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("--out", default="site")
    s.add_argument("--local-dir", help="copy from this folder instead of the GitHub release (tests)")
    sub.add_parser("queue")
    sub.add_parser("status")
    sub.add_parser("schema")
    args = ap.parse_args()
    return {"stage": cmd_stage, "queue": cmd_queue, "status": cmd_status, "schema": cmd_schema}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
