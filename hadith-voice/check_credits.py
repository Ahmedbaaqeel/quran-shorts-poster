"""Read-only: print the ElevenLabs plan, credits used/left and the next reset. Costs nothing."""
import json, os, sys, urllib.request
from datetime import datetime, timezone
KEY = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("No ELEVENLABS_API_KEY")
req = urllib.request.Request("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": KEY})
s = json.loads(urllib.request.urlopen(req, timeout=60).read())
keep = {k: s.get(k) for k in ("tier", "character_count", "character_limit", "next_character_count_reset_unix",
                              "can_extend_character_limit", "allowed_to_extend_character_limit", "status", "billing_period")}
if keep.get("next_character_count_reset_unix"):
    keep["next_reset_utc"] = datetime.fromtimestamp(keep["next_character_count_reset_unix"], timezone.utc).isoformat()
keep["left"] = (keep.get("character_limit") or 0) - (keep.get("character_count") or 0)
print(json.dumps(keep, indent=1))
os.makedirs(os.environ.get("OUT_DIR") or "out", exist_ok=True)
json.dump(keep, open(os.path.join(os.environ.get("OUT_DIR") or "out", "credits.json"), "w"), indent=1)
