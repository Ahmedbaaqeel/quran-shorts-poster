"""Make the hadith narration with ElevenLabs, in 3 different native-Arabic male voices.
Needs ELEVENLABS_API_KEY in the environment or in a .env file next to this script. Python stdlib only.
Writes eleven/<n>-<voice>.mp3 and eleven/<n>-<voice>.json (character timings) next to this script."""
import base64, json, os, re, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("OUT_DIR") or os.path.join(HERE, "eleven")
KEY = os.environ.get("ELEVENLABS_API_KEY")
for envf in (os.path.join(HERE, ".env"), os.path.join(os.path.dirname(HERE), ".env")):
    if not KEY and os.path.exists(envf):
        for line in open(envf, encoding="utf-8-sig"):
            if line.strip().startswith("ELEVENLABS_API_KEY"):
                KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
if not KEY:
    sys.exit("No ELEVENLABS_API_KEY found (env var or .env file)")

TEXT = """تخيّل… أن تُكتَبَ لك حسناتُ غيرِك.
قال رسولُ اللهِ صلّى اللهُ عليه وسلّم:
مَن دَلَّ على خَيرٍ، فلَهُ مِثلُ أجرِ فاعِلِه.
كلمةٌ تقولُها… فيعملُ بها غيرُك.
ثم يدُلُّ هو غيرَه… وغيرَه.
وأنت… لك مثلُ أجرِ من عمِل.
فدُلَّ على الخير… ولو بمشاركةِ هذا المقطع."""
SETTINGS = {"stability": 0.45, "similarity_boost": 0.8, "style": 0.3, "use_speaker_boost": True}


def api(method, path, body=None, query=None):
    url = "https://api.elevenlabs.io" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:300]!r}")


def pick_voices(n=3):
    res = api("GET", "/v1/shared-voices", query={"page_size": 40, "language": "ar", "gender": "male", "sort": "usage_character_count_1y"})
    voices = res.get("voices", [])
    good = [v for v in voices if (v.get("use_case") or "") in ("narrative_story", "informative_educational", "narration", "conversational", "social_media")]
    chosen = (good + [v for v in voices if v not in good])[:n]
    print("Picked:", [(v["name"], v.get("accent"), v.get("use_case")) for v in chosen])
    return chosen


def main():
    os.makedirs(OUT, exist_ok=True)
    own = api("GET", "/v1/voices").get("voices", [])
    mine = {v["voice_id"] for v in own}
    try:
        cands = pick_voices()
    except RuntimeError as e:
        print("voice library not available:", e); cands = []
    # fallback: the built-in multilingual male narrators
    cands += [dict(v, public_owner_id=None) for v in own if v.get("category") == "premade" and v["name"].split()[0] in ("Brian", "Daniel", "George", "Adam")]
    done = 0
    for k, v in enumerate(cands, 1):
        if done >= 3: break
        vid = v["voice_id"]
        if vid not in mine and v.get("public_owner_id"):
            try:
                vid = api("POST", f"/v1/voices/add/{v['public_owner_id']}/{v['voice_id']}", {"new_name": v["name"][:40]})["voice_id"]
            except RuntimeError as e:
                print("could not add voice", v["name"], e); continue
        try:
            r = api("POST", f"/v1/text-to-speech/{vid}/with-timestamps", {"text": TEXT, "model_id": "eleven_multilingual_v2", "voice_settings": SETTINGS},
                    query={"output_format": "mp3_44100_128"})
        except RuntimeError as e:
            print("tts failed for", v["name"], e); continue
        slug = re.sub(r"[^A-Za-z0-9]+", "-", v["name"]).strip("-")[:30] or f"voice{k}"
        base = os.path.join(OUT, f"{k}-{slug}")
        open(base + ".mp3", "wb").write(base64.b64decode(r["audio_base64"]))
        json.dump({"voice": v["name"], "accent": v.get("accent"), "text": TEXT, "alignment": r.get("alignment") or r.get("normalized_alignment")},
                  open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False)
        print("wrote", base + ".mp3"); done += 1


main()
