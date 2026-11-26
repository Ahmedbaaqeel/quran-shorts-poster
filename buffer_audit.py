#!/usr/bin/env python3
"""Show what Buffer still has for the Haditho_97 channel, and optionally remove it.

  python buffer_audit.py            list (read-only)
  CLEAR=1 python buffer_audit.py    also delete every post still queued for haditho_97

Also prints the last Instagram posts on haditho_97 (needs IG_ACCESS_TOKEN).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("ACCOUNT", "hadith")
import post  # noqa: E402

CLEAR = os.environ.get("CLEAR", "") not in ("", "0", "false")


def tdesc(t):
    return t["name"] or f"{t['kind']}({tdesc(t['ofType'])})"


T = "type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }"
qf = post.gql(f"query {{ __schema {{ queryType {{ fields {{ name args {{ name {T} }} }} }} }} }}")["__schema"]["queryType"]["fields"]
pf = next(f for f in qf if f["name"] == "posts")
print("posts args:", [(a["name"], tdesc(a["type"])) for a in pf["args"]])


def show_input(name, depth=0):
    ty = post.gql(f'query($n:String!){{__type(name:$n){{kind inputFields{{name {T}}} enumValues{{name}}}}}}', {"n": name})["__type"]
    if not ty:
        return
    print("  " * depth + name + ":", [(f["name"], tdesc(f["type"])) for f in ty.get("inputFields") or []] or [e["name"] for e in ty.get("enumValues") or []])
    if depth < 2:
        for f in ty.get("inputFields") or []:
            t = f["type"]
            while t.get("ofType"):
                t = t["ofType"]
            if t["kind"] in ("INPUT_OBJECT", "ENUM"):
                show_input(t["name"], depth + 1)


arg_t = pf["args"][0]["type"]
while arg_t.get("ofType"):
    arg_t = arg_t["ofType"]
show_input(arg_t["name"])

orgs = post.gql("query { account { organizations { id name } } }")["account"]["organizations"]
chans = []
for o in orgs:
    for c in post.gql("query($org: OrganizationId!) { channels(input: {organizationId: $org}) { id name service } }", {"org": o["id"]})["channels"]:
        chans.append((o["id"], c))
hadith = [(o, c) for o, c in chans if post._norm(c["name"]) == "haditho_97"]
print("channels:", [(c["name"], c["service"], c["id"]) for _, c in chans])
if not hadith:
    raise SystemExit("no haditho_97 channel in Buffer")
org, ch = hadith[0]

found = []
for status in ("scheduled", "sent", "error"):
    try:
        res = post.gql("""query($i: PostsInput!) { posts(input: $i, first: 50) { edges { node { id status dueAt sentAt text } } } }""",
                       {"i": {"organizationId": org, "filter": {"channelIds": [ch["id"]], "status": [status]}}})
    except SystemExit as exc:
        print(f"posts query ({status}) failed: {exc}")
        continue
    for e in res["posts"]["edges"]:
        n = e["node"]
        found.append(n)
        print(f"{status:9} id={n['id']} due={n.get('dueAt')} sent={n.get('sentAt')} text={(n.get('text') or '')[:60]!r}")

if CLEAR:
    for n in found:
        if str(n.get("status", "")).lower() in ("scheduled", "draft", "needs_approval", "pending"):
            r = post.gql("mutation($i: DeletePostInput!) { deletePost(input: $i) { __typename } }", {"i": {"id": n["id"]}})
            print("deleted", n["id"], json.dumps(r))
