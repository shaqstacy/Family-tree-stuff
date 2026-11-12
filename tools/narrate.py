#!/usr/bin/env python3
"""Pre-record narration for the Stories section with Piper (offline text-to-speech).

Everything runs on this machine: story text is never sent to a voice service.
Only the voice model itself is downloaded once, from the Piper project.

Usage:
  pip install piper-tts            (in a virtualenv)
  download a voice, e.g. en_US-norman-medium.onnx + .onnx.json from
  https://huggingface.co/rhasspy/piper-voices
  python tools/narrate.py path/to/en_US-norman-medium.onnx "Norman"

Writes media/narration/<story-id>.mp3 and the NARRATION block in index.html
(where each paragraph starts, so the page can highlight along). A story whose
text has changed since it was recorded falls back to the device voice until
this script is run again; unchanged stories are skipped.
"""
import json, os, re, subprocess, sys, tempfile, wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
OUT = os.path.join(ROOT, 'media', 'narration')
GAP_TITLE, GAP_PARA = 1.0, 0.7   # seconds of quiet after the title and between paragraphs
PACE = 1.08                      # >1 is slower; a calm storyteller's pace


def load(name):
    js = ("const fs=require('fs');const h=fs.readFileSync(process.argv[1],'utf8');"
          "const m=h.match(new RegExp('const '+process.argv[2]+' = ([\\\\[{][^\\\\n]*[\\\\]}]);\\\\n'))"
          "||h.match(new RegExp('const '+process.argv[2]+' = ([\\\\[{][\\\\s\\\\S]*?\\\\n[\\\\]}]);'));"
          "process.stdout.write(JSON.stringify(eval('('+m[1]+')')));")
    return json.loads(subprocess.check_output(['node', '-e', js, HTML, name]))


def fnv(s):
    # FNV-1a over UTF-16 code units; the page computes the same to spot edited stories
    h = 0x811c9dc5
    b = s.encode('utf-16-le')
    for i in range(0, len(b), 2):
        h ^= b[i] | (b[i + 1] << 8)
        h = (h * 0x01000193) & 0xffffffff
    return format(h, '08x')


def source(c, lessons):
    return '\n'.join([c['title'], c['when'], *c['body'], (c.get('pull') or {}).get('q', ''), *(lessons if c.get('lessons') else [])])


def spoken(t):
    t = re.sub(r'(\d{4})s?\s*[–-]\s*(\d{4}|today)', r'\1 to \2', t)
    t = re.sub(r'\bc\.\s*', 'about ', t)
    t = re.sub(r'\s+&\s+', ' and ', t)
    return t.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")


def parts(c, lessons):
    # same order as the page: title, first paragraph, pull quote, the rest, then the lessons list
    p = [spoken(c['title'] + '. ' + (c['when'] + '.' if re.search(r'\d', c['when']) else ''))]
    body = c['body']
    if body:
        p.append(spoken(body[0]))
    if c.get('pull'):
        p.append(spoken('"' + c['pull']['q'] + '" ' + c['pull'].get('by', '')))
    p += [spoken(x) for x in body[1:]]
    if c.get('lessons'):
        p += [spoken(x) for x in lessons]
    return p


def main():
    model, label = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'Piper')
    from piper import PiperVoice, SynthesisConfig
    voice = PiperVoice.load(model)
    cfg = SynthesisConfig(length_scale=PACE)
    chapters, lessons = load('CHAPTERS'), load('LESSONS')
    os.makedirs(OUT, exist_ok=True)
    m = re.search(r'const NARRATION = (\{[\s\S]*?\n\});', open(HTML, encoding='utf-8').read())
    old = json.loads(m.group(1)) if m else {'ch': {}}
    if old.get('voice') != label:
        old = {'ch': {}}
    nar = {'voice': label, 'ch': {}}
    for c in chapters:
        h = fnv(source(c, lessons))
        mp3 = os.path.join(OUT, c['id'] + '.mp3')
        prev = old['ch'].get(c['id'])
        if prev and prev['h'] == h and os.path.exists(mp3):
            nar['ch'][c['id']] = prev
            continue
        with tempfile.TemporaryDirectory() as td:
            out_wav = os.path.join(td, 'all.wav')
            starts, w = [], None
            for i, text in enumerate(parts(c, lessons)):
                pw = os.path.join(td, f'{i}.wav')
                with wave.open(pw, 'wb') as f:
                    voice.synthesize_wav(text, f, syn_config=cfg)
                with wave.open(pw, 'rb') as f:
                    if w is None:
                        w = wave.open(out_wav, 'wb'); w.setparams(f.getparams()); rate = f.getframerate(); width = f.getsampwidth() * f.getnchannels(); total = 0
                    starts.append(round(total / rate, 2))
                    fr = f.readframes(f.getnframes()); w.writeframes(fr); total += len(fr) // width
                gap = GAP_TITLE if i == 0 else GAP_PARA
                n = int(rate * gap); w.writeframes(b'\x00' * n * width); total += n
            w.close()
            subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-i', out_wav, '-ac', '1', '-b:a', '48k', mp3])
        nar['ch'][c['id']] = {'h': h, 't': starts, 'd': round(total / rate, 1)}
        print(f"{c['id']}: {len(starts)} parts, {total / rate / 60:.1f} min", flush=True)
    for f in os.listdir(OUT):  # drop audio for stories that no longer exist
        if f.endswith('.mp3') and f[:-4] not in nar['ch']:
            os.remove(os.path.join(OUT, f))
    s = open(HTML, encoding='utf-8').read()
    block = 'const NARRATION = ' + json.dumps(nar, indent=1, ensure_ascii=False) + ';'
    if m:
        s = s.replace(m.group(0), block)
    else:
        s = s.replace('/* ---------- Narration', block + '\n/* ---------- Narration', 1)
    open(HTML, 'w', encoding='utf-8').write(s)
    print('total', round(sum(x['d'] for x in nar['ch'].values()) / 60, 1), 'min')


if __name__ == '__main__':
    main()
