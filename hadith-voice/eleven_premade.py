"""Free-plan takes: ElevenLabs' built-in narrators reading the Arabic narration with the v3 model
(better accents than multilingual v2), forced to Arabic. Writes OUT_DIR/v3-<voice>.mp3 + .json."""
import base64, json, os, re, sys, urllib.parse, urllib.request

KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = open(os.path.join(HERE, "narration.txt"), encoding="utf-8").read().strip()
WANT = ("George", "Brian", "Daniel", "Bill")


def api(method, path, body=None, query=None):
    url = "https://api.elevenlabs.io" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:400]!r}")


os.makedirs(OUT, exist_ok=True)
voices = [v for v in api("GET", "/v1/voices").get("voices", []) if v.get("category") == "premade" and v["name"].split()[0] in WANT]
print("premade:", [v["name"] for v in voices])
for v in voices:
    slug = re.sub(r"[^A-Za-z]+", "", v["name"].split()[0])
    for model, settings in (("eleven_v3", {"stability": 0.5}), ("eleven_multilingual_v2", {"stability": 0.5, "similarity_boost": 0.8, "style": 0.2})):
        body = {"text": TEXT, "model_id": model, "voice_settings": settings, "language_code": "ar"}
        try:
            r = api("POST", f"/v1/text-to-speech/{v['voice_id']}/with-timestamps", body, query={"output_format": "mp3_44100_128"})
        except RuntimeError as e:
            print("failed", v["name"], model, e)
            continue
        base = os.path.join(OUT, f"{'v3' if model == 'eleven_v3' else 'v2ar'}-{slug}")
        open(base + ".mp3", "wb").write(base64.b64decode(r["audio_base64"]))
        json.dump({"voice": v["name"], "model": model, "text": TEXT, "alignment": r.get("alignment") or r.get("normalized_alignment")},
                  open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False)
        print("wrote", base)
