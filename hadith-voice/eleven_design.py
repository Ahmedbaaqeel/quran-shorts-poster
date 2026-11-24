"""Free-plan route to a native Arabic narrator: design custom voices from a description (ElevenLabs
Voice Design), save them to the account, then read the narration with word timings.
Library voices need a paid plan, designed voices don't. Needs ELEVENLABS_API_KEY. Python stdlib only.
Writes OUT_DIR/d<n>.mp3 + d<n>.json (character timings)."""
import base64, json, os, sys, urllib.parse, urllib.request

KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TEXT = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "narration.txt"), encoding="utf-8").read().strip()
SETTINGS = {"stability": 0.5, "similarity_boost": 0.85, "style": 0.25, "use_speaker_boost": True}
DESIGNS = [
    ("Hadith Narrator Saudi", "A calm, deep, warm middle-aged Saudi Arabic man narrating an Islamic reminder in clear classical Arabic (fusha). Sincere, gentle and heartfelt, slow measured pace with natural pauses. Close-mic studio recording, no background noise."),
    ("Hadith Narrator Soft", "A soft-spoken young Arabic man with a gentle, emotional, touching voice telling a short Islamic story in Modern Standard Arabic. Warm and intimate, like a heartfelt social media reminder. Clean studio audio."),
]


def api(method, path, body=None, query=None):
    url = "https://api.elevenlabs.io" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:400]!r}")


def design(desc):
    body = {"voice_description": desc, "text": TEXT, "auto_generate_text": False}
    for path, extra in (("/v1/text-to-voice/design", {"model_id": "eleven_multilingual_ttv_v2"}), ("/v1/text-to-voice/create-previews", {})):
        try:
            return api("POST", path, dict(body, **extra))["previews"]
        except RuntimeError as e:
            print("design via", path, "failed:", e)
    return []


def save(name, desc, gid):
    for path, body in (("/v1/text-to-voice", {"voice_name": name, "voice_description": desc, "generated_voice_id": gid}),
                       ("/v1/text-to-voice/create-voice-from-preview", {"voice_name": name, "voice_description": desc, "generated_voice_id": gid})):
        try:
            return api("POST", path, body)["voice_id"]
        except RuntimeError as e:
            print("save via", path, "failed:", e)


def main():
    os.makedirs(OUT, exist_ok=True)
    existing = {v["name"]: v["voice_id"] for v in api("GET", "/v1/voices").get("voices", [])}
    n = 0
    for name, desc in DESIGNS:
        if name in existing:
            vids = [existing[name]]
        else:
            previews = design(desc)
            print(name, "->", len(previews), "previews")
            vids = []
            # keep the first preview of each design as an account voice (free plan: 3 custom voices)
            if previews:
                vid = save(name, desc, previews[0]["generated_voice_id"])
                if vid: vids.append(vid)
        for vid in vids:
            try:
                r = api("POST", f"/v1/text-to-speech/{vid}/with-timestamps",
                        {"text": TEXT, "model_id": "eleven_multilingual_v2", "voice_settings": SETTINGS}, query={"output_format": "mp3_44100_128"})
            except RuntimeError as e:
                print("tts failed", name, e); continue
            n += 1
            open(os.path.join(OUT, f"d{n}.mp3"), "wb").write(base64.b64decode(r["audio_base64"]))
            json.dump({"voice": name, "description": desc, "text": TEXT, "alignment": r.get("alignment") or r.get("normalized_alignment")},
                      open(os.path.join(OUT, f"d{n}.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print("wrote", f"d{n}.mp3", name)


if __name__ == "__main__":
    main()
