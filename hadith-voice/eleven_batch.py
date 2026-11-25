"""Batch of DEFAULT voice-overs (same settings as eleven_default.py: Meisam, eleven_v3, stability 0.5, one take each).
For every name in batch_list.txt, reads batch/<name>.txt and writes OUT_DIR/<name>.mp3 + .json.
Skips names whose mp3 already exists, so a re-run only pays for missing takes."""
import base64, json, os, sys, urllib.request, urllib.error
KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
VID = open(os.path.join(HERE, "voice_id.txt")).read().strip()
names = [n.strip() for n in open(os.path.join(HERE, "batch_list.txt"), encoding="utf-8") if n.strip() and not n.startswith("#")]
os.makedirs(OUT, exist_ok=True)
fail = 0
for name in names:
    if os.path.exists(os.path.join(OUT, name + ".mp3")):
        print("skip", name); continue
    text = open(os.path.join(HERE, "batch", name + ".txt"), encoding="utf-8").read().strip()
    body = {"text": text, "model_id": "eleven_v3", "language_code": "ar",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True}}
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VID}/with-timestamps?output_format=mp3_44100_128",
                                 method="POST", data=json.dumps(body).encode(), headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=300)
        r = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"::warning::{name} failed {e.code}: {e.read()[:300]!r}"); fail += 1; continue
    open(os.path.join(OUT, name + ".mp3"), "wb").write(base64.b64decode(r["audio_base64"]))
    json.dump({"text": text, "voice_id": VID, "model": "eleven_v3", "alignment": r.get("alignment")},
              open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("wrote", name, len(text), "chars", "cost header:", resp.headers.get("character-cost") or resp.headers.get("x-character-count"))
sys.exit(1 if fail == len(names) and fail else 0)
