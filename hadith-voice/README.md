# Haditho_97 voice-overs

`eleven_batch.py` records each narration in `batch/<name>.txt` listed in `batch_list.txt` with ElevenLabs (voice in `voice_id.txt`, eleven_v3) and commits `out/<name>.mp3/.json`. It only runs when `run.txt` changes on a `claude/` branch, because every recording costs credits. Names that already have an mp3 in `out/` are skipped.
