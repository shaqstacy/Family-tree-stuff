# Oral history kit

Transcribes family recordings with WhisperX and recognizes who is talking, entirely on your own computer. See the top of `oral.py` for the commands.

Status: written and syntax-checked, but not yet run end to end. The local Claude Code session that sets it up should test it on one short recording first and fix anything that has changed in WhisperX or pyannote.

Never commit `recordings/`, `transcripts/`, `voices/` or `hf_token.txt`; `.gitignore` excludes them.
