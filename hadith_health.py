#!/usr/bin/env python3
"""Daily health check for the Haditho_97 posting (runs on GitHub Actions).

Checks, using the hadith Buffer account (BUFFER_API_KEY) and the files in hadith/:
  1. posts due in the last 36 hours really went out (Buffer status "sent")
  2. the Buffer queue holds exactly one post for every scheduled day in the
     queue_ahead window, at the right time, with no duplicates or strays
  3. every scheduled day through the end of the schedule has its video file
     (right size, hook card at the start) and an Arabic-only caption
  4. the Haditho_97 Buffer workflow ran recently without failures

Safe fixes it makes on its own (unless DRY_RUN=1):
  - a queued post missing from Buffer is queued again (post.py queue)
  - a duplicate queued post (same day, same caption) is deleted from Buffer
  - a post Buffer marked as failed is retried once, about 10 minutes later
  - a scheduled day that was never queued and is already due is posted now

Writes hadith/health.json and the GitHub job summary. Standard library only
(plus ffmpeg for the hook check).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ACCOUNT", "hadith")
import post  # noqa: E402

DRY_RUN = os.environ.get("DRY_RUN", "") not in ("", "0", "false")
TZ = post.TZ
NOW = datetime.now(timezone.utc)
TODAY = NOW.astimezone(TZ).date()
HEALTH = post.DATA / "health.json"
# Posts queued before this went through the old shared Buffer account, which this key cannot see.
HADITH_BUFFER_SINCE = datetime(2026, 11, 27, tzinfo=timezone.utc)
ALLOWED_LATIN = {"Haditho_97", "Shorts"}
WANTED_FIELDS = ["id", "status", "dueAt", "sentAt", "createdAt", "text", "externalLink", "error", "errorMessage"]

problems: list[str] = []
fixed: list[str] = []
info: list[str] = []


def ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def local(dt: datetime | None) -> str:
    return dt.astimezone(TZ).strftime("%a %d %b %H:%M") if dt else "?"


# ---------------------------------------------------------------- Buffer

def post_fields() -> str:
    """Ask Buffer which of the fields we want its Post type has (the API changes)."""
    ty = post.gql('query { __type(name: "Post") { fields { name type { kind name ofType { kind name } } } } }')["__type"]
    have = {f["name"]: f for f in (ty or {}).get("fields") or []}
    out = []
    for name in WANTED_FIELDS:
        f = have.get(name)
        if not f:
            continue
        t = f["type"]
        kind = t["kind"] if t["kind"] != "NON_NULL" else t["ofType"]["kind"]
        tname = t["name"] or t["ofType"]["name"]
        if kind in ("SCALAR", "ENUM"):
            out.append(name)
        elif kind == "OBJECT":
            sub = post.gql('query($n:String!){ __type(name:$n){ fields { name type { kind ofType { kind } } } } }', {"n": tname})["__type"]
            scal = [s["name"] for s in sub["fields"] if (s["type"]["kind"] in ("SCALAR", "ENUM")
                    or (s["type"].get("ofType") or {}).get("kind") in ("SCALAR", "ENUM"))][:4]
            if scal:
                out.append(f"{name} {{ {' '.join(scal)} }}")
    return " ".join(out or ["id", "status", "dueAt", "text"])


def buffer_posts() -> tuple[dict, list[dict]]:
    orgs = post.gql("query { account { organizations { id name } } }")["account"]["organizations"]
    channel = None
    for o in orgs:
        for c in post.gql("query($org: OrganizationId!) { channels(input: {organizationId: $org}) "
                          "{ id name service isDisconnected isLocked isQueuePaused } }", {"org": o["id"]})["channels"]:
            if c["service"].lower() == "instagram" and post.channel_wanted("instagram", c["name"]):
                channel = (o["id"], c)
    if not channel:
        raise SystemExit("No haditho_97 Instagram channel in the hadith Buffer account")
    org, ch = channel
    fields = post_fields()
    found: dict[str, dict] = {}
    for status in ("scheduled", "sent", "error"):
        after = None
        for _ in range(10):
            q = ("query($i: PostsInput!, $a: String) { posts(input: $i, first: 50, after: $a) "
                 f"{{ edges {{ node {{ {fields} }} }} pageInfo {{ hasNextPage endCursor }} }} }}")
            inp = {"organizationId": org, "filter": {"channelIds": [ch["id"]], "status": [status]}}
            try:
                res = post.gql(q, {"i": inp, "a": after})["posts"]
            except SystemExit:
                try:  # older API shape without paging
                    res = post.gql("query($i: PostsInput!) { posts(input: $i, first: 50) "
                                   f"{{ edges {{ node {{ {fields} }} }} }} }}", {"i": inp})["posts"]
                except SystemExit as exc:
                    problems.append(f"Could not read Buffer '{status}' posts: {exc}")
                    break
            for e in res["edges"]:
                n = e["node"]
                n["status"] = str(n.get("status") or status).lower()
                found[n["id"]] = n
            pi = res.get("pageInfo") or {}
            if not pi.get("hasNextPage"):
                break
            after = pi.get("endCursor")
    return ch, list(found.values())


def delete_post(pid: str) -> None:
    post.gql("mutation($i: DeletePostInput!) { deletePost(input: $i) { __typename } }", {"i": {"id": pid}})


# ---------------------------------------------------------------- video + caption checks

def has_hook(path: Path) -> bool | None:
    """The green question card sits across the upper third at ~0.8 s."""
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.8", "-i", str(path), "-frames:v", "1", "-vf",
                              "crop=iw*0.5:ih*0.03:iw*0.25:ih*0.335,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(raw) < 3:
        return None
    r, g, b = raw[0], raw[1], raw[2]
    return r + g + b < 450 and g >= r and g > b


def caption_issue(text: str) -> str | None:
    words = set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", text))
    bad = sorted(w for w in words if w not in ALLOWED_LATIN)
    if bad:
        return "has non-Arabic words: " + ", ".join(bad[:6])
    if "#Haditho_97" not in text:
        return "is missing #Haditho_97"
    return None


def norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


# ---------------------------------------------------------------- GitHub runs

def workflow_runs() -> None:
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        info.append("Workflow history not checked (no GitHub token).")
        return
    since = (NOW - timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for wf in ("hadith-buffer.yml",):
        url = f"https://api.github.com/repos/{repo}/actions/workflows/{wf}/runs?per_page=20&created=%3E{since}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        try:
            runs = json.loads(urllib.request.urlopen(req, timeout=30).read())["workflow_runs"]
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Could not read {wf} runs: {exc}")
            continue
        bad = [r for r in runs if r.get("conclusion") in ("failure", "timed_out", "startup_failure")]
        ok = [r for r in runs if r.get("conclusion") == "success"]
        for r in bad:
            problems.append(f"{wf} run failed at {local(ts(r['created_at']))} Riyadh: {r['html_url']}")
        if not ok:
            problems.append(f"{wf} has not run successfully in the last 26 hours (scheduled runs may be late or off).")
        else:
            info.append(f"{wf}: {len(ok)} successful run(s) in the last 26 hours, {len(bad)} failed.")


# ---------------------------------------------------------------- main check

def run_queue(env_extra: dict) -> bool:
    if DRY_RUN:
        info.append(f"DRY RUN: would run post.py queue {env_extra or ''}")
        return True
    env = {**os.environ, **env_extra}
    r = subprocess.run([sys.executable, str(ROOT / "post.py"), "queue"], env=env, capture_output=True, text=True)
    print(r.stdout + r.stderr, flush=True)
    return r.returncode == 0


def check(final: bool) -> dict:
    posted = post.load_posted()
    sched = post.SCHEDULE["videos"]
    by_file = {e["file"]: e for e in sched}
    ch, bposts = buffer_posts()
    byid = {p["id"]: p for p in bposts}
    for flag in ("isDisconnected", "isLocked", "isQueuePaused"):
        if ch.get(flag):
            problems.append(f"The Buffer Instagram channel is {flag[2:].lower()}: nothing will post until it is fixed in Buffer.")

    # id -> (posted key, record)
    known = {}
    for key, rec in posted.items():
        ig = rec.get("instagram")
        if isinstance(ig, dict) and ig.get("buffer_post_id") and (ts(ig.get("queued_at")) or NOW) >= HADITH_BUFFER_SINCE:
            known[ig["buffer_post_id"]] = (key, rec)

    needs_queue = False
    handled: set[str] = set()  # posted keys already dealt with in the "last 36 hours" check
    # 1. posts due in the last 36 hours
    recent = []
    for pid, (key, rec) in known.items():
        bp = byid.get(pid)
        # Buffer's own time wins: a post may have been moved in Buffer after it was queued.
        due = ts((bp or {}).get("dueAt")) or ts((bp or {}).get("sentAt")) or ts(rec["instagram"].get("due"))
        if due and NOW - timedelta(hours=36) <= due <= NOW - timedelta(minutes=5):
            recent.append((due, pid, key, rec))
    for due, pid, key, rec in sorted(recent):
        handled.add(key)
        bp = byid.get(pid)
        name = f"{rec['file']} ({local(due)})"
        if bp and bp["status"] == "sent":
            link = bp.get("externalLink") or ""
            info.append(f"Posted: {name} at {local(ts(bp.get('sentAt')))} {link}".rstrip())
            vid = post.DATA / "videos" / rec["file"]
            if key >= "2026-11-28" and vid.exists() and has_hook(vid) is False:
                problems.append(f"{name} went out without the hook card at the start.")
            issue = caption_issue(bp.get("text") or "")
            if issue and key >= "2026-11-28":
                problems.append(f"Caption of {name} {issue}.")
        elif bp and bp["status"] == "error":
            err = json.dumps(bp.get("error") or bp.get("errorMessage") or "")[:200]
            if "instagram_failed" in rec or final:
                problems.append(f"Buffer could not publish {name} {err}. Already retried once; needs a look.")
            else:
                if not DRY_RUN:
                    rec["instagram_failed"] = rec.pop("instagram")
                    post.save_posted(posted)
                ok = run_queue({"POST_FILE": rec["file"]})
                (fixed if ok else problems).append(f"{name} failed in Buffer {err}; " + ("re-posted it, due in about 10 minutes." if ok else "re-posting it also failed."))
        elif bp and bp["status"] == "scheduled":
            if NOW - due > timedelta(minutes=45):
                problems.append(f"{name} is still waiting in Buffer {int((NOW - due).total_seconds() // 60)} minutes after its time.")
        else:
            # Not in Buffer under that id. Look for a sent post with the same caption.
            cap = norm_text(by_file.get(rec["file"], {}).get("caption", ""))
            twin = next((p for p in bposts if p["status"] == "sent" and cap and norm_text(p.get("text")) == cap), None)
            if twin:
                info.append(f"Posted: {name} (found by caption)")
            else:
                problems.append(f"{name} is not in Buffer at all (deleted in Buffer?). Not sure it went out.")

    # 2. today's / overdue regular days that were never queued
    for e in sched:
        if post.is_extra(e) or e["date"] != TODAY.isoformat():
            continue
        elsewhere = any(r.get("file") == e["file"] for k, r in posted.items() if k != e["date"])
        if not elsewhere and (e["date"] not in posted or not any(k.startswith("instagram") for k in posted[e["date"]])):
            if post.due_time(datetime.fromisoformat(e["date"]).date()) <= NOW + timedelta(minutes=11) and not final:
                ok = run_queue({"POST_FILE": e["file"]})
                (fixed if ok else problems).append(f"{e['date']} ({e['file']}) was never queued; " + ("posting it now." if ok else "posting it failed."))

    # 3. the queue window
    window = [e for e in post.upcoming(TODAY)]
    scheduled = [p for p in bposts if p["status"] == "scheduled"]
    seen_ids = set()
    for e in window:
        rec = posted.get(e["date"], {})
        ig = rec.get("instagram") or {}
        bp = byid.get(ig.get("buffer_post_id", ""))
        want = post.due_time(datetime.fromisoformat(e["date"]).date())
        if bp and bp["status"] == "sent":
            continue
        if e["date"] in handled or "instagram_failed" in rec:
            continue
        if any(r.get("file") == e["file"] for k, r in posted.items() if k != e["date"]):
            continue  # posted under another key; post.py never queues it twice
        if ig and ts(ig.get("due")) and ts(ig["due"]) <= NOW:
            continue  # already due: handled by the "last 36 hours" check above
        if not bp or bp["status"] != "scheduled":
            if final:
                problems.append(f"{e['date']} ({e['file']}) is not queued in Buffer.")
            else:
                if ig and not DRY_RUN:
                    n = sum(1 for k in rec if k.startswith("instagram_lost"))
                    rec[f"instagram_lost{n or ''}"] = rec.pop("instagram")
                    post.save_posted(posted)
                needs_queue = True
                fixed.append(f"{e['date']} ({e['file']}) was missing from the Buffer queue; queued it again.")
            continue
        seen_ids.add(bp["id"])
        due = ts(bp.get("dueAt"))
        if due and abs((due - want).total_seconds()) > 120 and want > NOW + timedelta(minutes=11):
            problems.append(f"{e['date']} is queued for {local(due)}, not {local(want)}.")
        if norm_text(bp.get("text")) != norm_text(e["caption"]):
            problems.append(f"{e['date']} caption in Buffer differs from schedule.json.")
        issue = caption_issue(bp.get("text") or "")
        if issue:
            problems.append(f"{e['date']} caption {issue}.")
    extras = []
    for p in scheduled:
        if p["id"] in seen_ids:
            continue
        if p["id"] in known:
            extras.append(f"{known[p['id']][1]['file']} at {local(ts(p.get('dueAt')))}")
            continue
        # A stray: a duplicate of a known queued post can go; anything else is reported.
        twin = next((q for q in scheduled if q["id"] != p["id"] and q["id"] in known
                     and norm_text(q.get("text")) == norm_text(p.get("text"))
                     and (ts(q.get("dueAt")) or NOW).astimezone(TZ).date() == (ts(p.get("dueAt")) or NOW).astimezone(TZ).date()), None)
        if twin and not final:
            if not DRY_RUN:
                delete_post(p["id"])
            fixed.append(f"Deleted a duplicate Buffer post for {local(ts(p.get('dueAt')))}.")
        else:
            problems.append(f"Unknown post in the Buffer queue at {local(ts(p.get('dueAt')))}: {(p.get('text') or '')[:50]!r}")
    days = {}
    for p in scheduled:
        d = (ts(p.get("dueAt")) or NOW).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
        days[d] = days.get(d, 0) + 1
    for d, n in days.items():
        if n > 1 and final:
            problems.append(f"{n} posts are queued for the same time {d}.")
    if len(scheduled) >= 10:
        problems.append(f"Buffer queue holds {len(scheduled)} posts; the free plan allows 10 per channel.")
    if needs_queue and not final:
        if not run_queue({}):
            problems.append("Re-queueing the missing posts failed (see the run log).")

    # 4. remaining videos
    left = [e for e in sched if not post.is_extra(e) and e["date"] > TODAY.isoformat()]
    dates = sorted(e["date"] for e in left)
    if dates:
        d = TODAY + timedelta(days=1)
        last = datetime.fromisoformat(dates[-1]).date()
        while d <= last:
            if d.isoformat() not in dates:
                problems.append(f"No video scheduled for {d}.")
            d += timedelta(days=1)
        dup = sorted({x for x in dates if dates.count(x) > 1})
        if dup:
            problems.append("More than one video on: " + ", ".join(dup))
    files_seen = {}
    for e in left:
        if e["file"] in files_seen:
            problems.append(f"{e['file']} is scheduled twice ({files_seen[e['file']]} and {e['date']}).")
        files_seen[e["file"]] = e["date"]
        vid = post.DATA / "videos" / e["file"]
        if not vid.exists():
            problems.append(f"{e['date']}: video file {e['file']} is missing.")
            continue
        if vid.stat().st_size != e["size"]:
            problems.append(f"{e['date']}: {e['file']} size does not match schedule.json.")
        if final:
            continue
        if has_hook(vid) is False:
            problems.append(f"{e['date']}: {e['file']} has no hook card at the start.")
        issue = caption_issue(e["caption"])
        if issue:
            problems.append(f"{e['date']} caption {issue}.")

    return {
        "videos_left": len(left),
        "last_date": dates[-1] if dates else None,
        "queued": sorted(f"{(ts(p.get('dueAt')) or NOW).astimezone(TZ):%Y-%m-%d %H:%M}" for p in scheduled),
        "queued_extras": extras,
    }


def main() -> int:
    first = check(final=False)
    workflow_runs()
    if fixed and not DRY_RUN:
        # Re-read Buffer and posted.json after the fixes and report what is still wrong.
        before = list(problems)
        problems.clear()
        summary = check(final=True)
        problems[:] = before + [p for p in problems if p not in before]
    else:
        summary = first
    info[:] = list(dict.fromkeys(info))
    result = {
        "checked_at": NOW.astimezone(TZ).isoformat(timespec="minutes"),
        "ok": not problems,
        "problems": problems,
        "fixed": fixed,
        "info": info,
        **summary,
    }
    if not DRY_RUN:
        HEALTH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        lines = [f"## Haditho_97 health {'✅ all good' if not problems else '⚠️ needs a look'}",
                 f"Checked {result['checked_at']} · {result['videos_left']} videos left (last {result['last_date']}) · "
                 f"{len(result['queued'])} queued in Buffer"]
        lines += ["", "### Problems"] + [f"- {p}" for p in problems] if problems else []
        lines += ["", "### Fixed"] + [f"- {p}" for p in fixed] if fixed else []
        lines += ["", "### Info"] + [f"- {p}" for p in info]
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
