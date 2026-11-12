// Builds the PUBLIC edition of the site: same design, but details of living people removed
// from the data itself (not just hidden), so they are not in the page source either.
// Usage: node tools/build_public.js <output-dir>
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '..');
const OUT = path.resolve(process.argv[2] || path.join(ROOT, 'dist-public'));
let h = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const { livingSet } = require('./living.js');

function block(name){
  const re = new RegExp('const ' + name + ' = ([\\[{][\\s\\S]*?\\n[\\]}]);');
  const m = h.match(re); if(!m) throw new Error('no block ' + name);
  return { val: eval('(' + m[1] + ')'), put: v => { h = h.replace(m[0], () => 'const ' + name + ' = ' + JSON.stringify(v, null, 1) + ';'); } };
}
const people = block('PEOPLE'); const PEOPLE = people.val;
const { living } = livingSet(PEOPLE);
const isLiving = id => living.has(id);

// Name tokens that identify a living person and no one who has died
const clean = s => (s||'').replace(/[“”"()]/g,' ');
const tok = p => new Set([p.first, ...(clean(p.short).split(/\s+/)), ...(clean(p.name).split(/\s+/)), ...((p.name||'').match(/“([^”]+)”/g)||[]).map(x=>x.replace(/[“”]/g,''))].filter(t=>t && t.length>2 && /^[A-Z]/.test(t)));
const deadTok = new Set(); PEOPLE.filter(p=>!isLiving(p.id)).forEach(p=>tok(p).forEach(t=>deadTok.add(t)));
const surnames = new Set(['Stacy','Folz','Zoglman','Campbell','Davis','Prichard','Barlow','Pruitt','Stewart','Hively','Schmitt','Stratman','Miller','Sears','Haller','Alvey','Mull','Stallings','Francis','Adkins','Hollingsworth']);
const liveTok = new Set(); PEOPLE.filter(p=>isLiving(p.id)).forEach(p=>{ const f=p.first||clean(p.name).split(/\s+/)[0]; [f, ...((p.name||'').match(/“([^”]+)”/g)||[]).map(x=>x.replace(/[“”]/g,''))].forEach(t=>{ if(t && t.length>2 && !deadTok.has(t) && !surnames.has(t)) liveTok.add(t); }); });
const nameRe = new RegExp('\\b(' + [...liveTok].map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|') + ')\\b');
const mentionsLiving = s => typeof s === 'string' && nameRe.test(s);
const scrubSentences = s => s.split(/(?<=[.!?”])\s+/).filter(x=>!mentionsLiving(x)).join(' ');

// PEOPLE: keep name, family and relationships; drop dates, places, photos and notes
people.put(PEOPLE.map(p => {
  if(!isLiving(p.id)) return p;
  const role = (p.role||'').split(' · ')[0];
  const keep = { id:p.id, name:p.name, fam:p.fam, par:p.par||[], sp:p.sp||[], living:true, role: /,|\d/.test(role) ? 'Living' : role, notes:[], src:[] };
  ['short','first','aka'].forEach(k=>{ if(p[k]) keep[k]=p[k]; });
  return keep;
}));
// MEDIA: drop photos showing a living person
const media = block('MEDIA'); const MEDIA = media.val;
Object.keys(MEDIA).forEach(k=>{ if((MEDIA[k].who||[]).some(isLiving)) delete MEDIA[k]; });
media.put(MEDIA);
// EVENTS
const ev = block('EVENTS'); ev.put(ev.val.filter(e=>!(e.who||[]).some(isLiving) && !mentionsLiving(e.t)));
// CHAPTERS: drop paragraphs naming living people; drop a chapter left empty
const ch = block('CHAPTERS'); ch.put(ch.val.map(c=>{
  const body=(c.body||[]).filter(par=>!mentionsLiving(par));
  const out={...c, body, who:(c.who||[]).filter(id=>!isLiving(id))};
  if(c.pull && mentionsLiving(c.pull.q)) delete out.pull;
  return out;
}).filter(c=>c.body.length));
// RECORDS: drop items only about living people, or that name them in the summary
const rec = block('RECORDS'); rec.put(rec.val.filter(r=>!((r.who||[]).length && r.who.every(isLiving))).map(r=>({...r, who:(r.who||[]).filter(id=>!isLiving(id)), sum: scrubSentences(r.sum||'')})));
// NOTES, PLACES, LINEAGE, HERITAGE
const no = block('NOTES'); no.put(no.val.filter(n=>!mentionsLiving(n.h+' '+n.p+' '+n.v)));
const pl = block('PLACES'); pl.put(pl.val.map(p=>({...p, items:p.items.filter(i=>!mentionsLiving(i))})).filter(p=>p.items.length));
const li = block('LINEAGE'); li.put(li.val.map(l=>(l.who||[]).some(isLiving)||mentionsLiving(l.text) ? {...l, text: scrubSentences(l.text) || 'Living. Details are kept private in this edition.'} : l));
const he = block('HERITAGE'); he.put(he.val.map(x=>({...x, text: scrubSentences(x.text||'')})));
// Map: homes and journeys
const lv = block('LIVED'); lv.put(lv.val.map(([k,ids,y,n])=>[k,ids.filter(id=>!isLiving(id)),y,n]).filter(([k,ids,y,n])=>ids.length && !mentionsLiving(n)));
const mv = block('MOVES'); mv.put(mv.val.map(m=>({...m, legs:m.legs.filter(l=>!mentionsLiving(l[3]))})).filter(m=>m.legs.length>0 && m.id!=='today'));
// Mark the edition
h = h.replace('const PUBLIC_EDITION = false;', 'const PUBLIC_EDITION = true;');

// Recorded narration reads the private stories aloud, living people included: leave it out here
if(/const NARRATION = /.test(h)){ const na=block('NARRATION'); na.put({voice:null, ch:{}}); }

// Write site + only the media still referenced
fs.rmSync(OUT, { recursive:true, force:true });
fs.mkdirSync(path.join(OUT,'media'), { recursive:true });
fs.writeFileSync(path.join(OUT,'index.html'), h);
const used = new Set([...h.matchAll(/media\/[A-Za-z0-9._-]+/g)].map(m=>m[0]));
used.forEach(f=>{ const src=path.join(ROOT,f); if(fs.existsSync(src) && fs.statSync(src).isFile()) fs.copyFileSync(src, path.join(OUT,f)); });
fs.writeFileSync(path.join(OUT,'README.md'), '# Stacy Family Tree (public edition)\n\nGenerated from the private family-tree-stuff repository by tools/build_public.js. Details of living family members (dates, places, photos and notes) are removed. Do not edit by hand.\n');
console.log(JSON.stringify({ living: living.size, media: used.size, tokens: [...liveTok].length, out: OUT }));
