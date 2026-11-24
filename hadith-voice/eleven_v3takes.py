"""Two v3 takes with the chosen voice (voice_id.txt), full harakat (narration_full.txt), read in one go.
A: plain natural reading. B: same text with v3 delivery cues. Writes OUT_DIR/v3take-A/B.mp3 + .json. ~2 x 290 credits."""
import base64, json, os, sys, urllib.parse, urllib.request

KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = open(os.path.join(HERE, "narration_full.txt"), encoding="utf-8").read().strip()
VID = open(os.path.join(HERE, "voice_id.txt")).read().strip()
L = TEXT.split("\n")
TAGGED = "[warm, heartfelt, calm] " + "\n".join(L[:5]) + "\n[softly] " + L[5] + "\n[warmly] " + L[6]
TAKES = [("A", TEXT), ("B", TAGGED)]


def api(path, body, query):
    url = "https://api.elevenlabs.io" + path + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode(),
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{path} -> {e.code}: {e.read()[:400]!r}")


os.makedirs(OUT, exist_ok=True)
for name, text in TAKES:
    body = {"text": text, "model_id": "eleven_v3", "language_code": "ar",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}}
    try:
        r = api(f"/v1/text-to-speech/{VID}/with-timestamps", body, {"output_format": "mp3_44100_128"})
    except RuntimeError as e:
        print("failed", name, e); continue
    base = os.path.join(OUT, f"v3take-{name}")
    open(base + ".mp3", "wb").write(base64.b64decode(r["audio_base64"]))
    json.dump({"voice_id": VID, "model": "eleven_v3", "text": text, "alignment": r.get("alignment") or r.get("normalized_alignment")},
              open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False)
    print("wrote", base, len(text), "chars")
