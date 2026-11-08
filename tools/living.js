// Works out who in PEOPLE is probably living, so the public edition can hide their details.
// Rule: no death date, and a known or estimated birth year of 1926 or later
// (estimated from parents, spouses and children when the person's own birth year is missing).
// People listed in ALWAYS_LIVING / NEVER_LIVING override the rule.
const yearOf = s => { const m = s && String(s).match(/(\d{4})/); return m ? +m[1] : null; };
const ALWAYS_LIVING = [];      // add ids here to force-hide someone
const NEVER_LIVING = ["mabel_davis"]; // known to have died; no date recorded
function livingSet(PEOPLE){
  const P = Object.fromEntries(PEOPLE.map(p=>[p.id,p]));
  const kids = {}; PEOPLE.forEach(p=>(p.par||[]).forEach(id=>(kids[id]=kids[id]||[]).push(p.id)));
  const est = {}; PEOPLE.forEach(p=>{ const y=yearOf(p.b); if(y) est[p.id]=y; });
  for(let pass=0; pass<8; pass++){
    PEOPLE.forEach(p=>{
      if(est[p.id]) return;
      const c=[];
      (p.par||[]).forEach(id=>{ if(est[id]) c.push(est[id]+27); });
      (kids[p.id]||[]).forEach(id=>{ if(est[id]) c.push(est[id]-27); });
      (p.sp||[]).forEach(id=>{ if(est[id]) c.push(est[id]); });
      const dy=yearOf(p.d); if(dy) c.push(dy-60);
      if(c.length) est[p.id]=Math.round(c.reduce((a,b)=>a+b,0)/c.length);
    });
  }
  const living = new Set();
  PEOPLE.forEach(p=>{
    if(NEVER_LIVING.includes(p.id)) return;
    if(ALWAYS_LIVING.includes(p.id)) { living.add(p.id); return; }
    if(p.d || p.dp || p.bur || p.dFlag) return;
    const y = est[p.id];
    if(y && y >= 1926) living.add(p.id);
  });
  return {living, est};
}
module.exports = { livingSet, yearOf };
