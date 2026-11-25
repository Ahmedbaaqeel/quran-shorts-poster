#!/usr/bin/env python3
"""Remove one queued Buffer post by id (used when a video moves off Buffer).

  BUFFER_POST_ID=<id> python buffer_remove.py

Prints the delete mutation Buffer offers, calls it, and clears the Buffer
record for that post from hadith/posted.json so the log matches.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("ACCOUNT", "hadith")
import post  # noqa: E402

pid = os.environ.get("BUFFER_POST_ID", "").strip()
if not pid:
    raise SystemExit("BUFFER_POST_ID is not set")

q = """query { __schema { mutationType { fields { name args { name type { kind name ofType { kind name ofType { kind name } } } } } } } }"""
fields = post.gql(q)["__schema"]["mutationType"]["fields"]
dels = [f for f in fields if "delete" in f["name"].lower() and "post" in f["name"].lower()]
for f in dels:
    print("mutation", f["name"], [(a["name"], a["type"]) for a in f["args"]])
m = next((f for f in dels if f["name"] == "deletePost"), dels[0] if dels else None)
if not m:
    raise SystemExit("Buffer has no delete-post mutation")

arg = m["args"][0]
t = arg["type"]
while t.get("ofType"):
    inner = t["ofType"]
    if not inner.get("name") and not inner.get("ofType"):
        break
    t = inner
tname = t["name"]
print("argument", arg["name"], "type", tname)
if tname and tname.endswith("Input"):
    it = post.gql('query($n:String!){__type(name:$n){inputFields{name}}}', {"n": tname})["__type"]["inputFields"]
    print("input fields", [f["name"] for f in it])
    value = {it[0]["name"]: pid} if len(it) == 1 else {"id": pid}
else:
    value = pid
gql_type = {"NON_NULL": "!"}.get(arg["type"]["kind"], "")
res = post.gql(f"mutation($v: {tname}{gql_type}) {{ {m['name']}({arg['name']}: $v) {{ __typename }} }}", {"v": value})
print("result", json.dumps(res))

posted = post.load_posted()
for day, rec in posted.items():
    ig = rec.get("instagram")
    if isinstance(ig, dict) and ig.get("buffer_post_id") == pid:
        rec["instagram_buffer_removed"] = rec.pop("instagram")
        print(f"log: {day} Buffer post marked removed")
post.save_posted(posted)
