"""Read the narration with ONE chosen ElevenLabs voice (hadith-voice/voice_id.txt), with word timings.
Writes OUT_DIR/final-<voice_id>.mp3 + .json. One call, about 310 credits."""
import base64, json, os, sys, urllib.parse, urllib.request

KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = open(os.path.join(HERE, "narration.txt"), encoding="utf-8").read().strip()
VID = open(os.path.join(HERE, "voice_id.txt")).read().strip()
SETTINGS = {"stability": 0.5, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}


def api(method, path, body=None, query=None):
    url = "https://api.elevenlabs.io" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:400]!r}")


name = VID
try:
    name = api("GET", f"/v1/voices/{VID}").get("name", VID)
except RuntimeError as e:
    print("voice not in account yet:", e)
    found = api("GET", "/v1/shared-voices", query={"voice_id": VID, "page_size": 5}).get("voices", [])
    found = [v for v in found if v["voice_id"] == VID] or found
    if found:
        name = found[0]["name"]
        VID = api("POST", f"/v1/voices/add/{found[0]['public_owner_id']}/{found[0]['voice_id']}", {"new_name": name[:40]})["voice_id"]
        print("added", name, VID)
os.makedirs(OUT, exist_ok=True)
r = api("POST", f"/v1/text-to-speech/{VID}/with-timestamps", {"text": TEXT, "model_id": "eleven_multilingual_v2", "voice_settings": SETTINGS},
        query={"output_format": "mp3_44100_128"})
base = os.path.join(OUT, f"final-{VID}")
open(base + ".mp3", "wb").write(base64.b64decode(r["audio_base64"]))
json.dump({"voice": name, "voice_id": VID, "text": TEXT, "alignment": r.get("alignment") or r.get("normalized_alignment")},
          open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False)
print("wrote", base, name)
