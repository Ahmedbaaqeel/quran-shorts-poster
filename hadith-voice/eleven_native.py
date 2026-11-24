"""Paid-plan takes: the best native Arabic male narrators from the ElevenLabs voice library.
Picks voices with a Saudi / Gulf / standard-Arabic accent and a narration use case, ranked by
how much they are used, reads the narration with word timings. Writes OUT_DIR/n<k>-<voice>.mp3 + .json."""
import base64, json, os, re, sys, urllib.parse, urllib.request

KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
OUT = os.environ.get("OUT_DIR") or "out"
HERE = os.path.dirname(os.path.abspath(__file__))
TEXT = open(os.path.join(HERE, "narration.txt"), encoding="utf-8").read().strip()
HOW_MANY = int(os.environ.get("HOW_MANY", "3"))
SETTINGS = {"stability": 0.5, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}
GOOD_ACCENT = ("saudi", "standard", "modern standard", "msa", "gulf", "khaleeji", "emirati", "kuwaiti", "jordanian", "levantine")
GOOD_USE = ("narrative_story", "informative_educational", "narration", "social_media")


def api(method, path, body=None, query=None):
    url = "https://api.elevenlabs.io" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read()[:400]!r}")


lib = api("GET", "/v1/shared-voices", query={"page_size": 100, "language": "ar", "gender": "male", "sort": "usage_character_count_1y"}).get("voices", [])
def score(v):
    acc = (v.get("accent") or "").lower(); use = (v.get("use_case") or "").lower()
    return (any(a in acc for a in GOOD_ACCENT), use in GOOD_USE, v.get("usage_character_count_1y") or 0)
lib.sort(key=score, reverse=True)
print("ranked:", [(v["name"], v.get("accent"), v.get("use_case"), v.get("usage_character_count_1y")) for v in lib[:10]])
own = {v["name"]: v["voice_id"] for v in api("GET", "/v1/voices").get("voices", [])}
os.makedirs(OUT, exist_ok=True)
done = 0
for v in lib:
    if done >= HOW_MANY: break
    name = v["name"][:40]
    vid = own.get(name)
    if not vid:
        try:
            vid = api("POST", f"/v1/voices/add/{v['public_owner_id']}/{v['voice_id']}", {"new_name": name})["voice_id"]
        except RuntimeError as e:
            print("could not add", name, e); continue
    try:
        r = api("POST", f"/v1/text-to-speech/{vid}/with-timestamps", {"text": TEXT, "model_id": "eleven_multilingual_v2", "voice_settings": SETTINGS},
                query={"output_format": "mp3_44100_128"})
    except RuntimeError as e:
        print("tts failed", name, e); continue
    done += 1
    slug = re.sub(r"[^A-Za-z0-9]+", "-", v["name"].split(" - ")[0]).strip("-") or f"voice{done}"
    base = os.path.join(OUT, f"n{done}-{slug}")
    open(base + ".mp3", "wb").write(base64.b64decode(r["audio_base64"]))
    json.dump({"voice": v["name"], "accent": v.get("accent"), "use_case": v.get("use_case"), "description": v.get("description"),
               "text": TEXT, "alignment": r.get("alignment") or r.get("normalized_alignment")},
              open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False)
    print("wrote", base, "|", v["name"], "|", v.get("accent"))
