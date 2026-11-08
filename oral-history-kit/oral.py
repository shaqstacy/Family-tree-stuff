#!/usr/bin/env python3
"""
Family oral history kit: transcribe recordings and recognize who is talking.
Everything runs on this computer. Audio is never uploaded anywhere.

Commands
  python oral.py transcribe          Transcribe every new recording in recordings/
  python oral.py speakers            List unnamed voices, with a sample line for each
  python oral.py name FILE SPK NAME  Teach a voice: e.g.  python oral.py name "Grandma 1998" SPEAKER_01 "Theresa Zoglman"
  python oral.py relabel             Re-apply the voice library to every transcript (fast, no re-transcribing)
  python oral.py voices              Show the people in the voice library

Folders (next to this script)
  recordings/   put your audio and video files here (subfolders are fine)
  transcripts/  results: a readable .txt, a .srt subtitle file and a .json file per recording
  voices/       the voice library: one small file per person you have named
  work/         temporary converted audio (safe to delete)
"""
import argparse, csv, datetime, json, os, re, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REC, OUT, VOICES, WORK = HERE / "recordings", HERE / "transcripts", HERE / "voices", HERE / "work"
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".wma", ".ogg", ".oga", ".opus", ".flac", ".amr", ".3gp",
             ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".aiff", ".aif", ".caf"}
CONFIG = HERE / "config.json"
DEFAULTS = {
    "model": "large-v3",          # most accurate; use "medium" or "small" on slow computers
    "language": "en",             # set to null to let Whisper detect the language
    "min_speakers": None,         # e.g. 2 if every recording has at least two people
    "max_speakers": None,         # e.g. 5 to stop it inventing extra speakers
    "match_threshold": 0.55,      # how sure the voice match must be (0-1); raise if it mislabels people
    "batch_size": 8,              # lower to 4 or 2 if you run out of memory
    "device": "auto",             # "cuda" for an NVIDIA graphics card, "cpu" otherwise
    "initial_prompt": "Family names: Stacy, Zoglman, Stallings, Folz, Campbell, Davis, Adkins, Prichard, Hively."
}

def cfg():
    c = dict(DEFAULTS)
    if CONFIG.exists():
        c.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    return c

def hf_token():
    t = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    f = HERE / "hf_token.txt"
    if not t and f.exists():
        t = f.read_text(encoding="utf-8").strip()
    return t or None

def device_choice(c):
    import torch
    if c["device"] != "auto":
        return c["device"]
    return "cuda" if torch.cuda.is_available() else "cpu"

def hms(t):
    t = int(round(t)); return f"{t//3600:02d}:{t%3600//60:02d}:{t%60:02d}"

def srt_time(t):
    ms = int(round((t - int(t)) * 1000)); t = int(t)
    return f"{t//3600:02d}:{t%3600//60:02d}:{t%60:02d},{ms:03d}"

def safe_name(rel):
    return re.sub(r"[^\w\- .]+", "_", str(rel.with_suffix("")).replace(os.sep, " - ")).strip()

def to_wav(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)]
    subprocess.run(cmd, check=True)

# ---------- voice library ----------
def load_library():
    import numpy as np
    lib = {}
    VOICES.mkdir(exist_ok=True)
    for f in VOICES.glob("*.npy"):
        lib[f.stem.replace("_", " ")] = np.load(f)
    return lib

def best_match(emb, lib, threshold):
    import numpy as np
    if emb is None or not lib:
        return None, 0.0
    e = emb / (np.linalg.norm(emb) + 1e-9)
    scores = {}
    for name, v in lib.items():
        vs = np.atleast_2d(v)
        vs = vs / (np.linalg.norm(vs, axis=1, keepdims=True) + 1e-9)
        scores[name] = float(np.max(vs @ e))
    name = max(scores, key=scores.get)
    return (name, scores[name]) if scores[name] >= threshold else (None, scores[name])

class Embedder:
    """Turns a stretch of someone's speech into a 'voiceprint' (a list of numbers)."""
    def __init__(self, device, token):
        import torch
        from pyannote.audio import Model, Inference
        try:
            model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM", token=token)
        except TypeError:
            model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM", use_auth_token=token)
        self.inf = Inference(model, window="whole", device=torch.device(device))
    def voice(self, audio, spans):
        # audio: 16 kHz mono numpy array (already in memory, so no extra audio libraries are needed)
        import numpy as np, torch
        from pyannote.core import Segment
        clip = {"waveform": torch.from_numpy(np.asarray(audio, dtype="float32"))[None, :], "sample_rate": 16000}
        vecs = []
        for s, e in spans:
            try:
                v = self.inf.crop(clip, Segment(s, e))
                vecs.append(np.asarray(v).reshape(-1) * (e - s))
            except Exception:
                pass
        if not vecs:
            return None
        return np.sum(vecs, axis=0)

def speaker_spans(segments, spk, max_spans=12):
    spans = sorted(((s["end"] - s["start"], s["start"], s["end"]) for s in segments
                    if s.get("speaker") == spk and s["end"] - s["start"] >= 1.5), reverse=True)[:max_spans]
    return [(min(a, b), max(a, b)) for _, a, b in [(d, s, min(e, s + 20)) for d, s, e in spans]]

# ---------- output ----------
def apply_names(data, lib, threshold):
    names = {}
    for spk, info in data.get("speakers", {}).items():
        if info.get("manual"):
            names[spk] = info["name"]; continue
        import numpy as np
        emb = np.array(info["embedding"]) if info.get("embedding") else None
        name, score = best_match(emb, lib, threshold)
        info["name"], info["score"] = name, round(score, 3)
        names[spk] = name
    return names

def label(spk, names):
    if not spk:
        return "Unknown"
    return names.get(spk) or spk.replace("SPEAKER_", "Speaker ")

def write_outputs(data, base):
    lib = load_library(); c = cfg()
    names = apply_names(data, lib, c["match_threshold"])
    (base.with_suffix(".json")).write_text(json.dumps(data, indent=1), encoding="utf-8")
    lines, srt, last, buf, start = [], [], None, [], 0
    for seg in data["segments"]:
        who = label(seg.get("speaker"), names)
        if who != last and buf:
            lines.append(f"[{hms(start)}] {last}: {' '.join(buf)}\n"); buf = []
        if who != last:
            start = seg["start"]; last = who
        buf.append(seg["text"].strip())
    if buf:
        lines.append(f"[{hms(start)}] {last}: {' '.join(buf)}\n")
    head = f"{data['source']}\nTranscribed {data['transcribed']} with Whisper {data['model']}. Speakers: " + \
           ", ".join(sorted(set(label(s, names) for s in data.get("speakers", {})))) + "\n\n"
    base.with_suffix(".txt").write_text(head + "\n".join(lines), encoding="utf-8")
    for i, seg in enumerate(data["segments"], 1):
        srt.append(f"{i}\n{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n{label(seg.get('speaker'), names)}: {seg['text'].strip()}\n")
    base.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")

def write_index():
    rows = []
    for j in sorted(OUT.glob("*.json")):
        d = json.loads(j.read_text(encoding="utf-8"))
        names = sorted(set((v.get("name") or k) for k, v in d.get("speakers", {}).items()))
        rows.append([d["source"], hms(d.get("duration", 0)), "; ".join(names), j.with_suffix(".txt").name])
    with open(OUT / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["recording", "length", "speakers", "transcript"]); w.writerows(rows)

# ---------- commands ----------
def cmd_transcribe(a):
    import whisperx
    c = cfg(); dev = device_choice(c); token = hf_token()
    compute = "float16" if dev == "cuda" else "int8"
    files = [p for p in sorted(REC.rglob("*")) if p.suffix.lower() in AUDIO_EXT]
    todo = [p for p in files if not (OUT / (safe_name(p.relative_to(REC)) + ".json")).exists()]
    print(f"{len(files)} recordings found, {len(todo)} still to do. Device: {dev}. Model: {c['model']}.")
    if not todo:
        return
    if not token:
        print("\nNo Hugging Face token found, so speakers will NOT be separated (see README, step 4).\n")
    OUT.mkdir(exist_ok=True); WORK.mkdir(exist_ok=True)
    asr_opts = {"initial_prompt": c["initial_prompt"]} if c.get("initial_prompt") else None
    try:
        model = whisperx.load_model(c["model"], dev, compute_type=compute, language=c["language"], asr_options=asr_opts)
    except TypeError:
        model = whisperx.load_model(c["model"], dev, compute_type=compute, language=c["language"])
    diar = emb = None
    if token:
        try:
            from whisperx.diarize import DiarizationPipeline
        except ImportError:
            DiarizationPipeline = whisperx.DiarizationPipeline
        try:
            diar = DiarizationPipeline(token=token, device=dev)
        except TypeError:
            diar = DiarizationPipeline(use_auth_token=token, device=dev)
        emb = Embedder(dev, token)
    align_cache = {}
    for n, src in enumerate(todo, 1):
        rel = src.relative_to(REC); base = OUT / safe_name(rel); t0 = time.time()
        print(f"\n[{n}/{len(todo)}] {rel}")
        try:
            wav = WORK / (safe_name(rel) + ".wav"); to_wav(src, wav)
            audio = whisperx.load_audio(str(wav)); dur = len(audio) / 16000
            res = model.transcribe(audio, batch_size=c["batch_size"])
            lang = res.get("language") or c["language"] or "en"
            if lang not in align_cache:
                align_cache[lang] = whisperx.load_align_model(language_code=lang, device=dev)
            am, meta = align_cache[lang]
            res = whisperx.align(res["segments"], am, meta, audio, dev, return_char_alignments=False)
            speakers = {}
            if diar:
                kw = {k: c[k] for k in ("min_speakers", "max_speakers") if c.get(k)}
                ds = diar(audio, **kw)
                res = whisperx.assign_word_speakers(ds, res)
                for spk in sorted({s.get("speaker") for s in res["segments"] if s.get("speaker")}):
                    v = emb.voice(audio, speaker_spans(res["segments"], spk))
                    speakers[spk] = {"embedding": v.tolist() if v is not None else None}
            segs = [{"start": round(s["start"], 2), "end": round(s["end"], 2), "speaker": s.get("speaker"),
                     "text": s["text"]} for s in res["segments"] if "start" in s]
            data = {"source": str(rel), "duration": round(dur, 1), "model": c["model"], "language": lang,
                    "transcribed": datetime.date.today().isoformat(), "segments": segs, "speakers": speakers}
            write_outputs(data, base)
            print(f"   done in {hms(time.time()-t0)} for {hms(dur)} of audio -> {base.name}.txt")
            if not a.keep_wav:
                wav.unlink(missing_ok=True)
        except KeyboardInterrupt:
            print("\nStopped. Run the same command again to continue where it left off."); break
        except Exception as e:
            print(f"   FAILED: {e}")
            (OUT / "errors.log").open("a", encoding="utf-8").write(f"{datetime.datetime.now()} {rel}: {e}\n")
    write_index()

def find_json(q):
    q = q.lower(); hits = [j for j in OUT.glob("*.json") if q in j.stem.lower()]
    if len(hits) != 1:
        sys.exit(f"'{q}' matches {len(hits)} transcripts. Use more of the file name.")
    return hits[0]

def cmd_speakers(a):
    lib = load_library(); c = cfg(); any_ = False
    for j in sorted(OUT.glob("*.json")):
        d = json.loads(j.read_text(encoding="utf-8")); names = apply_names(d, lib, c["match_threshold"])
        for spk, info in d.get("speakers", {}).items():
            if a.all or not names.get(spk):
                sample = max((s for s in d["segments"] if s.get("speaker") == spk), key=lambda s: len(s["text"]), default=None)
                who = names.get(spk) or "?"
                print(f"{j.stem}  {spk}  [{who}]  {hms(sample['start']) if sample else ''}  \"{(sample or {}).get('text','').strip()[:90]}\"")
                any_ = True
    if not any_:
        print("Every voice has a name.")

def cmd_name(a):
    import numpy as np
    j = find_json(a.file); d = json.loads(j.read_text(encoding="utf-8"))
    info = d.get("speakers", {}).get(a.speaker)
    if not info or not info.get("embedding"):
        sys.exit(f"No voiceprint for {a.speaker} in {j.stem}. Run 'python oral.py speakers --all' to see the labels.")
    VOICES.mkdir(exist_ok=True); f = VOICES / (re.sub(r"[^\w\- ]", "", a.name).replace(" ", "_") + ".npy")
    v = np.array(info["embedding"])[None, :]
    if f.exists():
        v = np.vstack([np.atleast_2d(np.load(f)), v])
    np.save(f, v)
    info["manual"] = True; info["name"] = a.name
    write_outputs(d, j.with_suffix(""))
    print(f"Saved {a.name}'s voice ({len(v)} sample{'s' if len(v)>1 else ''}). Now run:  python oral.py relabel")

def cmd_relabel(a):
    n = 0
    for j in sorted(OUT.glob("*.json")):
        d = json.loads(j.read_text(encoding="utf-8")); write_outputs(d, j.with_suffix("")); n += 1
    write_index(); print(f"Relabeled {n} transcripts. Summary: transcripts/index.csv")

def cmd_voices(a):
    lib = load_library()
    print("\n".join(f"{k}  ({len(v) if v.ndim>1 else 1} sample(s))" for k, v in sorted(lib.items())) or "No voices named yet.")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcribe"); t.add_argument("--keep-wav", action="store_true"); t.set_defaults(f=cmd_transcribe)
    s = sub.add_parser("speakers"); s.add_argument("--all", action="store_true", help="also show voices that already have names"); s.set_defaults(f=cmd_speakers)
    n = sub.add_parser("name"); n.add_argument("file"); n.add_argument("speaker"); n.add_argument("name"); n.set_defaults(f=cmd_name)
    sub.add_parser("relabel").set_defaults(f=cmd_relabel)
    sub.add_parser("voices").set_defaults(f=cmd_voices)
    a = ap.parse_args()
    for d in (REC, OUT): d.mkdir(exist_ok=True)
    a.f(a)
