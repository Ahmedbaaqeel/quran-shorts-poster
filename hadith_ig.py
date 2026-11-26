#!/usr/bin/env python3
"""Post the Haditho_97 videos straight to Instagram with Meta's own API.

No Buffer and no third-party service: GitHub Actions calls Meta's official
Instagram API (Facebook login setup, graph.facebook.com) at post time.
IG_ACCESS_TOKEN is the access token of the Facebook Page that Haditho_97 is
linked to. A Page token made from a long-lived user token does not expire.

Commands:
  python hadith_ig.py check     read-only: show which account the token belongs to
                                and how many posts it may still publish today
  python hadith_ig.py post      publish today's video from hadith/schedule.json
                                once it is post time (hadith/config.json "post_time")

Environment:
  IG_ACCESS_TOKEN  Instagram user access token (GitHub secret)
  DRY_RUN=1        post: print what would happen, publish nothing
  POST_NOW=1       post: publish the next unposted video right away (tests)
  POST_FILE=x.mp4  post: publish this scheduled video right away, logged under
                   its own date (remove its Buffer post first)
  MAX_WAIT_MIN     post: if started before post time, wait up to this many
                   minutes for it (default 45)
  TODAY            override today's date, YYYY-MM-DD (tests only)

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "hadith"
CONFIG = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
SCHEDULE = json.loads((DATA / "schedule.json").read_text(encoding="utf-8"))
POSTED_PATH = DATA / "posted.json"
TZ = ZoneInfo(CONFIG["timezone"])
API_VERSION = CONFIG.get("ig_api_version", "v25.0")
GRAPH = f"https://graph.facebook.com/{API_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{API_VERSION}"
DRY_RUN = os.environ.get("DRY_RUN", "") not in ("", "0", "false")
POST_NOW = os.environ.get("POST_NOW", "") not in ("", "0", "false")
PLATFORM = "instagram_direct"  # key in hadith/posted.json
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # captions are Arabic


def log(msg: str) -> None:
    print(msg, flush=True)


def gh_warning(msg: str) -> None:
    print(f"::warning::{msg}", flush=True)


def token() -> str:
    t = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not t:
        raise SystemExit("IG_ACCESS_TOKEN is not set. Add it under Settings > Secrets and variables > Actions.")
    return t


def today() -> date:
    if os.environ.get("TODAY"):
        return date.fromisoformat(os.environ["TODAY"])
    return datetime.now(TZ).date()


def load_posted() -> dict:
    return json.loads(POSTED_PATH.read_text(encoding="utf-8")) if POSTED_PATH.exists() else {}


def save_posted(posted: dict) -> None:
    POSTED_PATH.write_text(json.dumps(posted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def request(method: str, url: str, params: dict | None = None, data: bytes | None = None,
            headers: dict | None = None, timeout: int = 120) -> dict:
    """Call the API; retry rate limits and server errors; never print the token."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"User-Agent": "haditho-poster", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()[:800].decode("utf-8", "replace")
            if (exc.code == 429 or exc.code >= 500) and attempt < 3:
                log(f"  HTTP {exc.code}, retrying in 30s")
                time.sleep(30)
                continue
            raise RuntimeError(f"HTTP {exc.code} from {url.split('?')[0]}: {raw}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                log(f"  network error {exc}, retrying in 20s")
                time.sleep(20)
                continue
            raise
    raise RuntimeError("API kept failing")


def me() -> dict:
    """The Instagram account linked to the token's Facebook Page: {"user_id", "username"}."""
    page = request("GET", f"{GRAPH}/me", {"fields": "name,instagram_business_account{id,username}", "access_token": token()})
    ig = page.get("instagram_business_account")
    if not ig:
        raise SystemExit(f"The token's Page ({page.get('name')}) has no linked Instagram professional account.")
    return {"user_id": ig["id"], "username": ig.get("username", ""), "page": page.get("name"), "account_type": "page-linked"}


def warn_if_access_ending() -> None:
    """Meta needs the Facebook owner to log in to the app about every 90 days ("data access")."""
    try:
        d = request("GET", f"{GRAPH}/debug_token", {"input_token": token(), "access_token": token()}).get("data", {})
    except RuntimeError as exc:
        log(f"(could not read the token's expiry: {exc})")
        return
    for key, what in (("expires_at", "The token"), ("data_access_expires_at", "Meta data access")):
        ts = int(d.get(key) or 0)
        if not ts:
            continue
        left = (datetime.fromtimestamp(ts, timezone.utc) - datetime.now(timezone.utc)).days
        log(f"{what} runs out on {datetime.fromtimestamp(ts, timezone.utc).date()} ({left} days)")
        if left <= 14:
            gh_warning(f"{what} for Haditho_97 runs out in {left} days. Open the app in Meta's Graph API Explorer and "
                       "generate the token again, then update IG_ACCESS_TOKEN.")


# ---------------------------------------------------------------- check

def cmd_check() -> int:
    info = me()
    warn_if_access_ending()
    log(f"Token is for Page '{info.get('page')}', Instagram @{info.get('username')} (id {info.get('user_id')})")
    want = str(CONFIG.get("channel_names", {}).get("instagram", "")).lower()
    if want and str(info.get("username", "")).lower() != want:
        raise SystemExit(f"This token is for @{info.get('username')}, not @{want}.")
    try:
        lim = request("GET", f"{GRAPH}/{info['user_id']}/content_publishing_limit",
                      {"fields": "quota_usage,config", "access_token": token()})
        log(f"Publishing limit: {json.dumps(lim.get('data', lim))}")
    except RuntimeError as exc:
        log(f"(could not read the publishing limit: {exc})")
    return 0


# ---------------------------------------------------------------- post

def post_time(day: date) -> datetime:
    hh, mm = (int(x) for x in CONFIG["post_time"].split(":"))
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)


def already_on_instagram(record: dict) -> bool:
    # Posted through Buffer (the queue before 2026-11-29) or by this script.
    return "instagram" in record or PLATFORM in record


def recent_captions(user_id: str) -> list[str]:
    res = request("GET", f"{GRAPH}/{user_id}/media", {"fields": "caption,timestamp", "limit": 10, "access_token": token()})
    return [m.get("caption") or "" for m in res.get("data", [])]


def create_container_resumable(user_id: str, entry: dict) -> str:
    res = request("POST", f"{GRAPH}/{user_id}/media", data=urllib.parse.urlencode({
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": entry["caption"],
        "share_to_feed": "true",
        **({"thumb_offset": str(CONFIG["thumbnail_offset_ms"])} if CONFIG.get("thumbnail_offset_ms") else {}),
        "access_token": token(),
    }).encode())
    cid = res["id"]
    path = DATA / "videos" / entry["file"]
    blob = path.read_bytes()
    log(f"  uploading {entry['file']} ({len(blob)} bytes)")
    up = request("POST", f"{RUPLOAD}/{cid}", data=blob, timeout=600, headers={
        "Authorization": f"OAuth {token()}", "offset": "0", "file_size": str(len(blob)),
        "Content-Type": "application/octet-stream"})
    if up and up.get("success") is False:
        raise RuntimeError(f"upload refused: {up}")
    return cid


def create_container_url(user_id: str, entry: dict, video_url: str) -> str:
    res = request("POST", f"{GRAPH}/{user_id}/media", data=urllib.parse.urlencode({
        "media_type": "REELS",
        "video_url": video_url,
        "caption": entry["caption"],
        "share_to_feed": "true",
        **({"thumb_offset": str(CONFIG["thumbnail_offset_ms"])} if CONFIG.get("thumbnail_offset_ms") else {}),
        "access_token": token(),
    }).encode())
    return res["id"]


def wait_until_ready(cid: str) -> None:
    for _ in range(60):  # up to 15 minutes
        st = request("GET", f"{GRAPH}/{cid}", {"fields": "status_code,status", "access_token": token()})
        code = st.get("status_code")
        log(f"  processing: {code}")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {st}")
        time.sleep(15)
    raise RuntimeError("Instagram took too long to process the video")


def publish(user_id: str, cid: str) -> str:
    res = request("POST", f"{GRAPH}/{user_id}/media_publish",
                  data=urllib.parse.urlencode({"creation_id": cid, "access_token": token()}).encode())
    return res["id"]


def cmd_post() -> int:
    t = today()
    posted = load_posted()
    done_files = {p.get("file") for d, p in posted.items() if already_on_instagram(p)}
    post_file = os.environ.get("POST_FILE", "").strip()
    if post_file:
        entry = next((e for e in SCHEDULE["videos"] if e["file"] == post_file), None)
        if not entry:
            raise SystemExit(f"POST_FILE: {post_file} is not in hadith/schedule.json")
        if PLATFORM in posted.get(entry["date"], {}):
            raise SystemExit(f"POST_FILE: {post_file} was already published directly; not posting it twice.")
        log(f"POST_FILE: publishing {post_file} (scheduled {entry['date']}) right now")
    elif POST_NOW:
        entry = next((e for e in SCHEDULE["videos"] if e["date"] >= t.isoformat() and e["file"] not in done_files), None)
        if not entry:
            raise SystemExit("POST_NOW: no unposted video left in the schedule.")
        log(f"POST_NOW: posting {entry['file']} (scheduled {entry['date']}) now, logged under {t}")
        entry = {**entry, "date": t.isoformat()}
    else:
        entry = next((e for e in SCHEDULE["videos"] if e["date"] == t.isoformat()), None)
        if not entry:
            gh_warning(f"Nothing scheduled for Haditho_97 on {t}.")
            return 0
        if already_on_instagram(posted.get(t.isoformat(), {})) or entry["file"] in done_files:
            log(f"{t}: {entry['file']} is already on Instagram. Nothing to do.")
            return 0
        due = post_time(t)
        now = datetime.now(TZ)
        if now < due:
            wait = (due - now).total_seconds()
            max_wait = int(os.environ.get("MAX_WAIT_MIN", "45")) * 60
            if wait > max_wait:
                log(f"Post time is {due.isoformat()}, {int(wait // 60)} min away. A later run will post it.")
                return 0
            log(f"Waiting {int(wait)}s until post time {due.isoformat()}")
            if not DRY_RUN:
                time.sleep(wait)

    if DRY_RUN:
        log(f"DRY RUN: would publish {entry['file']} as a Reel with caption:\n{entry['caption'][:300]}")
        if os.environ.get("IG_ACCESS_TOKEN"):
            cmd_check()
        return 0

    info = me()
    warn_if_access_ending()
    uid = info["user_id"]
    want = str(CONFIG.get("channel_names", {}).get("instagram", "")).lower()
    if want and str(info.get("username", "")).lower() != want:
        raise SystemExit(f"IG_ACCESS_TOKEN is for @{info.get('username')}, not @{want}. Nothing posted.")
    # Last guard against a double post (e.g. the log commit failed after a publish).
    head = entry["caption"].strip()[:120]
    if any(c.strip()[:120] == head for c in recent_captions(uid)):
        log(f"{entry['file']} is already on @{info['username']} (caption found). Logging it, not posting again.")
        posted.setdefault(entry["date"], {"file": entry["file"]})[PLATFORM] = {"found_existing": True,
                                                                               "logged_at": datetime.now(timezone.utc).isoformat()}
        save_posted(posted)
        return 0

    try:
        cid = create_container_resumable(uid, entry)
        how = "upload"
    except RuntimeError as exc:
        base = os.environ.get("VIDEO_BASE_URL", "").rstrip("/")
        if not base:
            raise
        log(f"Direct upload failed ({exc}); trying the public link instead")
        cid = create_container_url(uid, entry, f"{base}/{entry['file']}")
        how = "url"
    wait_until_ready(cid)
    media_id = publish(uid, cid)
    posted.setdefault(entry["date"], {"file": entry["file"]})[PLATFORM] = {
        "media_id": media_id, "via": how, "published_at": datetime.now(timezone.utc).isoformat()}
    save_posted(posted)
    log(f"{entry['date']}: published {entry['file']} to @{info['username']} (media {media_id})")
    return 0


def cmd_recent() -> int:
    info = me()
    res = request("GET", f"{GRAPH}/{info['user_id']}/media",
                  {"fields": "timestamp,media_type,caption,permalink", "limit": 10, "access_token": token()})
    for m in res.get("data", []):
        log(f"{m.get('timestamp')}  {m.get('media_type')}  {m.get('permalink')}  {(m.get('caption') or '')[:50]!r}")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    cmds = {"check": cmd_check, "post": cmd_post, "recent": cmd_recent}
    if cmd not in cmds:
        raise SystemExit(f"usage: python hadith_ig.py {'|'.join(cmds)}")
    return cmds[cmd]()


if __name__ == "__main__":
    sys.exit(main())
