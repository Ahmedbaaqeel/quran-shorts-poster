"""DEFAULT voice-over (Jos's pick, 2026-11-25 "Take B heartfelt"): one continuous eleven_v3 take of
narration_full.txt (full harakat, one phrase per line, may contain [warm, heartfelt, calm] / [softly] / [warmly] cues)
with voice_id.txt (Meisam). Writes OUT_DIR/<NAME or 'take'>.mp3 + .json. ~1 credit per character incl. harakat."""
import base64, json, os, sys, urllib.request
KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = open(os.path.join(HERE, "narration_full.txt"), encoding="utf-8").read().strip()
VID = open(os.path.join(HERE, "voice_id.txt")).read().strip()
NAME = (open(os.path.join(HERE, "take_name.txt")).read().strip() if os.path.exists(os.path.join(HERE, "take_name.txt")) else "take")
body = {"text": TEXT, "model_id": "eleven_v3", "language_code": "ar",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}}
req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VID}/with-timestamps?output_format=mp3_44100_128", method="POST",
                             data=json.dumps(body).encode(), headers={"xi-api-key": KEY, "Content-Type": "application/json"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
except urllib.error.HTTPError as e:
    sys.exit(f"failed {e.code}: {e.read()[:400]!r}")
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, NAME + ".mp3"), "wb").write(base64.b64decode(r["audio_base64"]))
json.dump({"text": TEXT, "voice_id": VID, "model": "eleven_v3", "alignment": r.get("alignment")},
          open(os.path.join(OUT, NAME + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
print("wrote", NAME, len(TEXT), "chars")
