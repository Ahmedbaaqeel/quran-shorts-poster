"""Short heartfelt v3 test with LOWER stability (0.0 = v3 'Creative'). Writes OUT_DIR/v3short-C.mp3 + .json. ~150 credits."""
import base64, json, os, sys, urllib.parse, urllib.request
KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
VID = open(os.path.join(HERE, "voice_id.txt")).read().strip()
L = open(os.path.join(HERE, "narration_full.txt"), encoding="utf-8").read().strip().split("\n")
TEXT = "[warm, heartfelt, calm] " + L[0] + "\n" + L[2] + "\n[softly] " + L[5]
body = {"text": TEXT, "model_id": "eleven_v3", "language_code": "ar",
        "voice_settings": {"stability": 0.0, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}}
req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VID}/with-timestamps?output_format=mp3_44100_128", method="POST",
                             data=json.dumps(body).encode(), headers={"xi-api-key": KEY, "Content-Type": "application/json"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
except urllib.error.HTTPError as e:
    sys.exit(f"failed {e.code}: {e.read()[:400]!r}")
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "v3short-C.mp3"), "wb").write(base64.b64decode(r["audio_base64"]))
json.dump({"text": TEXT, "stability": 0.0, "alignment": r.get("alignment")}, open(os.path.join(OUT, "v3short-C.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("wrote v3short-C", len(TEXT), "chars")
