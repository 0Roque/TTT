"use strict";
/* Read-only tournament viewer. All data comes from data/<code>.json. */

const QUORUM = 6;            // minimum players needed to start the tournament
const MAX_PLAYERS = 40;      // 8 groups of 5
const CODE_RE = /^[a-z0-9]{32}$/;
const GL = i => String.fromCharCode(65 + i);
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ROUND_NAME = {2:"Final",4:"Semi-finals",8:"Quarter-finals",16:"Round of 16"};
const ROUND_ONE  = {2:"Final",4:"Semi-final",8:"Quarter-final",16:"Round of 16"};

/* ---------- format logic ---------- */
const koSize = G => G === 1 ? 2 : Math.pow(2, Math.ceil(Math.log2(2*G)));   // knockout size (power of 2)
const thirdsNeeded = G => G === 1 ? 0 : koSize(G) - 2*G;                     // best 3rd places needed
function formats(N){
  const out = [];
  for(const G of [1,2,3,4,6,7,8]){
    if(G < Math.ceil(N/5) || G > Math.floor(N/3)) continue;                  // groups of 3–5 players
    const K = koSize(G), T = thirdsNeeded(G);
    if(T > G) continue;
    const base = Math.floor(N/G), ex = N % G;
    out.push({G, K, T, sizes: Array.from({length:G}, (_, i) => base + (i < ex ? 1 : 0))});
  }
  return out;
}
function recommended(N){
  const fm = formats(N); let best = fm[0];
  for(const f of fm){
    const d = Math.abs(f.G - N/4), db = Math.abs(best.G - N/4);
    if(d < db - 1e-9 || (Math.abs(d - db) < 1e-9 && f.G > best.G)) best = f;
  }
  return best;
}

/* ---------- round robin ---------- */
function rr(ps){
  const a = [...ps]; if(a.length % 2) a.push(null);
  const n = a.length, rounds = [];
  for(let r=0; r<n-1; r++){
    const m = [];
    for(let i=0; i<n/2; i++){ const x=a[i], y=a[n-1-i]; if(x!==null && y!==null) m.push(r%2 ? [y,x] : [x,y]); }
    rounds.push(m);
    a.splice(1, 0, a.pop());
  }
  return rounds;
}
const groupRounds = (t, gi) => rr(t.groups[gi]);
const groupMatches = (t, gi) => groupRounds(t, gi).flat();

/* ---------- results ---------- */
const pairKey = (x, y) => x < y ? `${x}-${y}` : `${y}-${x}`;
const lookup = (map, a, b) => { const r = map.get(pairKey(a, b)); return r ? (r.a === a ? r.sets : r.sets.map(([x,y]) => [y,x])) : null; };
function summ(sets){ let a=0,b=0,pa=0,pb=0; for(const [x,y] of sets){ if(x>y) a++; else b++; pa+=x; pb+=y; } return {a,b,pa,pb}; }
function validSet(x, y){
  if(!Number.isInteger(x) || !Number.isInteger(y) || x<0 || y<0) return false;
  const hi = Math.max(x,y), lo = Math.min(x,y);
  if(hi < 11) return false; if(hi === 11) return lo <= 9; return hi - lo === 2;
}
function parseSet(s){
  if(typeof s === "string"){ const m = s.trim().match(/^(\d+)\s*[-:]\s*(\d+)$/); return m ? [+m[1], +m[2]] : null; }
  if(Array.isArray(s) && s.length === 2) return [Number(s[0]), Number(s[1])];
  return null;
}
/* Parses one {a, b, sets} entry. Returns {a, b, sets} with player indices, or pushes a warning and returns null. */
function parseMatch(t, e, where){
  const label = `${where}: ${esc(e && e.a)} vs ${esc(e && e.b)}`;
  if(!e || typeof e !== "object"){ t.warn.push(`${where}: entry is not an object.`); return null; }
  const a = t.idx.get(String(e.a ?? "").trim().toLowerCase()), b = t.idx.get(String(e.b ?? "").trim().toLowerCase());
  if(a === undefined){ t.warn.push(`${label} — unknown player "${esc(e.a)}".`); return null; }
  if(b === undefined){ t.warn.push(`${label} — unknown player "${esc(e.b)}".`); return null; }
  if(a === b){ t.warn.push(`${label} — a player cannot play themselves.`); return null; }
  if(!Array.isArray(e.sets) || !e.sets.length) return null;                 // no sets yet = not played
  const need = (t.bestOf + 1) / 2, sets = []; let wa = 0, wb = 0;
  for(let i=0; i<e.sets.length; i++){
    const s = parseSet(e.sets[i]);
    if(!s || !validSet(s[0], s[1])){ t.warn.push(`${label} — set ${i+1} (${esc(JSON.stringify(e.sets[i]))}) is not a valid score (first to 11, win by 2).`); return null; }
    if(wa === need || wb === need){ t.warn.push(`${label} — the match was already decided before set ${i+1}.`); return null; }
    sets.push(s); s[0] > s[1] ? wa++ : wb++;
  }
  if(wa < need && wb < need){ t.warn.push(`${label} — not finished yet (${wa}–${wb}, best of ${t.bestOf}). Ignored until complete.`); return null; }
  return {a, b, sets};
}
function statsFor(ps, ms){
  const st = {}; ps.forEach(p => st[p] = {p:0,w:0,l:0,sw:0,sl:0,pw:0,pl:0});
  for(const m of ms){
    if(!(m.a in st) || !(m.b in st)) continue;
    const s = summ(m.sets), A = st[m.a], B = st[m.b];
    A.p++; B.p++; A.sw+=s.a; A.sl+=s.b; B.sw+=s.b; B.sl+=s.a; A.pw+=s.pa; A.pl+=s.pb; B.pw+=s.pb; B.pl+=s.pa;
    if(s.a > s.b){ A.w++; B.l++; } else { B.w++; A.l++; }                     // 1 point per win
  }
  return st;
}
/* Ranking: wins (= points) → sets won → points scored across all sets → head-to-head (2 tied) → seed order */
const cmpStats = (A, B) => B.w - A.w || B.sw - A.sw || B.pw - A.pw;
function playedMatches(t, gi){ return groupMatches(t, gi).map(([a,b]) => ({a, b, sets:lookup(t.gr, a, b)})).filter(m => m.sets); }
function groupDone(t, gi){ return groupMatches(t, gi).every(([a,b]) => lookup(t.gr, a, b)); }
function rankGroup(t, gi){
  const ps = t.groups[gi], st = statsFor(ps, playedMatches(t, gi));
  const order = [...ps].sort((x,y) => cmpStats(st[x], st[y]) || ps.indexOf(x) - ps.indexOf(y));
  for(let i=0; i+1<order.length; i++){
    const x = order[i], y = order[i+1];
    if(cmpStats(st[x], st[y]) !== 0) continue;
    if(i > 0 && cmpStats(st[order[i-1]], st[x]) === 0) continue;                       // 3+ tied
    if(i+2 < order.length && cmpStats(st[y], st[order[i+2]]) === 0) continue;
    const h = lookup(t.gr, x, y);
    if(h){ const s = summ(h); if(s.b > s.a){ order[i] = y; order[i+1] = x; } }
  }
  return {order, st};
}
function thirdsTable(t){
  const rows = [];
  t.groups.forEach((g, gi) => {
    if(g.length < 3) return;
    const r = rankGroup(t, gi), pid = r.order[2], s = r.st[pid], per = v => s.p ? v / s.p : 0;
    rows.push({g:gi, pid, s, done:groupDone(t, gi), wpm:per(s.w), swpm:per(s.sw), pwpm:per(s.pw)});
  });
  rows.sort((a,b) => b.wpm - a.wpm || b.swpm - a.swpm || b.pwpm - a.pwpm || a.g - b.g);
  return rows;
}

/* ---------- knockout structure ---------- */
function buildPairs(G, T){
  if(G === 1) return [[{t:"W",g:0},{t:"R",g:0}]];
  const pairs = [];
  for(let i=0; i<T; i++) pairs.push([{t:"W",g:i},{t:"3",s:i,vs:i}]);
  const avail = [...Array(G).keys()];
  for(let i=T; i<G; i++){
    const x = i ^ 1;
    const p = (x < G && x !== i && avail.includes(x)) ? x : avail.find(v => v !== i);
    avail.splice(avail.indexOf(p), 1);
    pairs.push([{t:"W",g:i},{t:"R",g:p}]);
  }
  for(let j=0; j<avail.length; j+=2) pairs.push([{t:"R",g:avail[j]},{t:"R",g:avail[j+1]}]);
  return arrange(pairs);
}
function meet(a, b){ let k=1; while(a!==b){ a>>=1; b>>=1; k++; } return k; }
function arrange(pairs){
  // place first-round matches so players from the same group (and group winners) meet as late as possible
  const M = pairs.length; if(M <= 2) return pairs;
  const R = Math.log2(M) + 1;
  const cost = order => {
    let c = 0; const toks = [];
    order.forEach((pi, slot) => pairs[pi].forEach(tk => toks.push([tk, slot])));
    for(let i=0;i<toks.length;i++) for(let j=i+1;j<toks.length;j++){
      const [a,sa] = toks[i], [b,sb] = toks[j]; if(sa === sb) continue;
      const w = R - meet(sa,sb) + 1;
      if(a.t!=="3" && b.t!=="3" && a.g===b.g) c += 100*w*w;
      if(a.t==="W" && b.t==="W") c += w*w;
    }
    return c;
  };
  let best = null, bc = Infinity; const used = Array(M).fill(false), cur = [0]; used[0] = true;
  (function rec(){
    if(cur.length === M){ const c = cost(cur); if(c < bc){ bc = c; best = [...cur]; } return; }
    for(let i=1;i<M;i++){ if(used[i]) continue; used[i]=true; cur.push(i); rec(); cur.pop(); used[i]=false; }
  })();
  return best.map(i => pairs[i]);
}
function assignThirds(t){
  const q = thirdsTable(t).slice(0, t.T), slots = [];
  t.pairs.forEach(p => p.forEach((tok, ti) => { if(tok.t === "3") slots.push({tok, opp:p[1-ti]}); }));
  const res = [], used = [];
  (function bt(i){
    if(i === slots.length) return true;
    for(let j=0;j<q.length;j++){
      if(used[j] || q[j].g === slots[i].opp.g) continue;
      used[j] = true; res[i] = q[j]; if(bt(i+1)) return true; used[j] = false;
    }
    return false;
  })(0);
  const map = {}; slots.forEach((s,i) => { if(res[i]) map[s.tok.s] = res[i].pid; });
  return map;
}
function koModel(t){
  const done = t.groups.every((_,gi) => groupDone(t, gi));
  const ranks = t.groups.map((_,gi) => groupDone(t, gi) ? rankGroup(t, gi).order : null);
  const tmap = done && t.T ? assignThirds(t) : {};
  const res = tok => tok.t==="W" ? (ranks[tok.g] ? ranks[tok.g][0] : null)
                   : tok.t==="R" ? (ranks[tok.g] ? ranks[tok.g][1] : null)
                   : (tmap[tok.s] ?? null);
  const lab = tok => {
    if(tok.t==="W") return `Winner Group ${GL(tok.g)}`;
    if(tok.t==="R") return `Runner-up Group ${GL(tok.g)}`;
    const others = t.groups.map((_,i)=>i).filter(i => i!==tok.vs).map(GL);
    return others.length <= 4 ? `Best 3rd ${others.join("/")}` : `Best 3rd (not ${GL(tok.vs)})`;
  };
  let num = 0;
  const mk = (a, b, la, lb, stage) => ({num:++num, a, b, la, lb, stage, sets:(a!=null && b!=null) ? lookup(t.kr, a, b) : null});
  const winner = m => m.sets ? (summ(m.sets).a > summ(m.sets).b ? m.a : m.b) : null;
  const loser  = m => m.sets ? (summ(m.sets).a > summ(m.sets).b ? m.b : m.a) : null;
  const rounds = [];
  let size = t.K;
  let prev = t.pairs.map(p => mk(res(p[0]), res(p[1]), lab(p[0]), lab(p[1]), ROUND_ONE[size]));
  rounds.push({name:ROUND_NAME[size], ms:prev});
  let third = null;
  while(prev.length > 1){
    size /= 2;
    const cur = [];
    for(let i=0;i<prev.length;i+=2) cur.push(mk(winner(prev[i]), winner(prev[i+1]), `Winner M${prev[i].num}`, `Winner M${prev[i+1].num}`, ROUND_ONE[size]));
    if(size === 2) third = mk(loser(prev[0]), loser(prev[1]), `Loser M${prev[0].num}`, `Loser M${prev[1].num}`, "3rd place");
    rounds.push({name:ROUND_NAME[size], ms:cur}); prev = cur;
  }
  const final = prev[0];
  return {rounds, third, champion:winner(final), runnerUp:loser(final), thirdPlace: third ? winner(third) : null, groupsDone:done, winner};
}

/* ---------- build tournament from JSON ---------- */
function build(data){
  const d = data && typeof data === "object" ? data : {};
  const t = {warn:[], name:String(d.name || "Table Tennis Tournament"), date:fmtDate(d.date), players:[], idx:new Map()};
  t.bestOf = [3,5,7].includes(d.bestOf) ? d.bestOf : 5;
  if(d.bestOf !== undefined && d.bestOf !== t.bestOf) t.warn.push(`"bestOf" must be 3, 5 or 7 — using best of 5.`);
  for(const raw of Array.isArray(d.players) ? d.players : []){
    const nm = String(raw ?? "").trim(); if(!nm) continue;
    const k = nm.toLowerCase();
    if(t.idx.has(k)){ t.warn.push(`Duplicate player "${esc(nm)}" ignored.`); continue; }
    t.idx.set(k, t.players.length); t.players.push(nm);
  }
  const N = t.players.length;
  t.quorum = N >= QUORUM;
  if(!t.quorum) return t;
  if(N > MAX_PLAYERS){ t.quorum = false; t.tooMany = true; return t; }

  // groups come only from the random draw made in the offline manager app; the page never draws them itself
  let groups = null;
  if(Array.isArray(d.groups) && d.groups.length){
    const seen = new Set(), g = [], problems = [];
    for(const grp of d.groups){
      const ids = [];
      for(const nm of Array.isArray(grp) ? grp : []){
        const id = t.idx.get(String(nm ?? "").trim().toLowerCase());
        if(id === undefined) problems.push(`unknown player "${esc(nm)}"`);
        else if(seen.has(id)) problems.push(`"${esc(nm)}" is in more than one group`);
        else { seen.add(id); ids.push(id); }
      }
      g.push(ids);
    }
    if(seen.size !== N) problems.push(`${N - seen.size} player(s) are not in any group`);
    if(g.some(x => x.length < 3)) problems.push("every group needs at least 3 players");
    if(g.length > 8) problems.push("at most 8 groups are supported");
    else if(thirdsNeeded(g.length) > g.length) problems.push(`${g.length} groups cannot fill a knockout bracket`);
    if(problems.length) t.warn.push(`"groups" ignored (${problems.join("; ")}). Make the draw again in the manager app.`);
    else groups = g;
  }
  if(!groups){ t.quorum = false; t.drawPending = true; return t; }   // quorum reached, draw not made yet
  t.drawnAt = d.drawnAt ? String(d.drawnAt) : "";
  t.groups = groups; t.G = groups.length; t.K = koSize(t.G); t.T = thirdsNeeded(t.G);
  t.sizes = groups.map(g => g.length); t.pairs = buildPairs(t.G, t.T);
  t.groupOf = {}; groups.forEach((g, gi) => g.forEach(p => t.groupOf[p] = gi));

  t.gr = new Map(); t.kr = new Map();
  for(const e of Array.isArray(d.groupResults) ? d.groupResults : []){
    const m = parseMatch(t, e, "Group result"); if(!m) continue;
    if(t.groupOf[m.a] !== t.groupOf[m.b]){ t.warn.push(`Group result: ${esc(t.players[m.a])} and ${esc(t.players[m.b])} are not in the same group — ignored.`); continue; }
    const k = pairKey(m.a, m.b);
    if(t.gr.has(k)){ t.warn.push(`Group result: ${esc(t.players[m.a])} vs ${esc(t.players[m.b])} is listed twice — only the first is used.`); continue; }
    t.gr.set(k, m);
  }
  for(const e of Array.isArray(d.knockoutResults) ? d.knockoutResults : []){
    const m = parseMatch(t, e, "Knockout result"); if(!m) continue;
    const k = pairKey(m.a, m.b);
    if(t.kr.has(k)){ t.warn.push(`Knockout result: ${esc(t.players[m.a])} vs ${esc(t.players[m.b])} is listed twice — only the first is used.`); continue; }
    t.kr.set(k, m);
  }
  return t;
}

/* ---------- phases ---------- */
function phaseOf(t, km){
  if(!t.quorum) return {key:"reg", label:"Registration"};
  if(!km.groupsDone) return {key:"groups", label:"Group stage"};
  for(const r of km.rounds) if(r.ms.some(m => !m.sets)) return {key:r.name, label:r.name};
  if(km.third && !km.third.sets) return {key:"Final", label:"3rd place match"};
  return {key:"done", label:"Finished"};
}
function stepsHTML(km, ph){
  const steps = [{key:"groups", label:"Group stage"}].concat(km.rounds.map(r => ({key:r.name, label:r.name})), [{key:"done", label:"Champion"}]);
  const ci = steps.findIndex(s => s.key === ph.key);
  return `<ol class="steps">${steps.map((s, i) => `<li class="${i < ci || ph.key === "done" ? "done" : i === ci ? "cur" : ""}"><span class="dot"></span><span class="lbl">${esc(s.label)}</span></li>`).join("")}</ol>`;
}

/* ---------- formatting ---------- */
function fmtDate(v){                         // shows dates as DD/MM/YYYY (accepts DD/MM/YYYY or YYYY-MM-DD in the file)
  const s = String(v ?? "").trim(), m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  return m ? `${m[3].padStart(2,"0")}/${m[2].padStart(2,"0")}/${m[1]}` : s;
}
const AV = ["#1a73e8","#188038","#c5221f","#e37400","#9334e6","#00796b","#d01884","#5f6368","#1967d2","#b06000"];
function avatar(nm){
  let h = 0; for(const c of nm) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  const ini = nm.split(/\s+/).filter(Boolean).slice(0, 2).map(w => [...w][0]).join("").toUpperCase();
  return `<span class="av" style="background:${AV[h % AV.length]}" aria-hidden="true">${esc(ini)}</span>`;
}
const pcell = (t, p) => `<td class="pl"><span class="pcell">${avatar(t.players[p])}${esc(t.players[p])}</span></td>`;
const setsText = sets => sets ? sets.map(([x,y]) => `${x}-${y}`).join(", ") : "";
const statCells = s => `<td>${s.p}</td><td class="b">${s.w}</td><td>${s.sw}</td><td>${s.pw}</td>`;
const statHeads = `<th title="Matches played">P</th><th title="Wins (1 point each)">W</th><th title="Sets won">SW</th><th title="Points scored across all sets">Pts</th>`;
const statKey = `<span>P: played</span><span>W: wins (1 point each)</span><span>SW: sets won</span><span>Pts: points scored in all sets</span>`;

/* one match, scoreboard style: each player row shows the points of every set; compact = bracket card */
function matchHTML(t, m, label, compact){
  const s = m.sets ? summ(m.sets) : null;
  const row = (p, ph, side) => {
    if(p == null) return `<div class="mr ph"><span class="av ph"></span><span class="nm">${esc(ph || "")}</span></div>`;
    const won = s && (side ? s.b > s.a : s.a > s.b), nm = t.players[p];
    const cells = s && !compact ? Array.from({length:t.bestOf}, (_, i) => m.sets[i]) : [];   // fixed width so columns line up
    const gs = cells.length ? `<span class="gs">${cells.map(x => x ? `<span class="g ${x[side] > x[1-side] ? "gw" : ""}">${x[side]}</span>` : `<span class="g"></span>`).join("")}</span>` : "";
    return `<div class="mr ${s ? (won ? "w" : "l") : ""}">${avatar(nm)}<span class="nm" title="${esc(nm)}">${esc(nm)}</span>${gs}<span class="tot">${s ? (side ? s.b : s.a) : ""}</span></div>`;
  };
  const status = s ? "Played" : (m.a != null && m.b != null) ? "Upcoming" : "";
  const rows = row(m.a, m.la, 0) + row(m.b, m.lb, 1);
  return compact
    ? `<div class="km"><div class="kmh"><span>${esc(label)}</span><span>${status}</span></div>${rows}${s ? `<div class="kset">${setsText(m.sets)}</div>` : ""}</div>`
    : `<div class="mt"><div class="mst"><b>${status}</b>${esc(label)}</div><div>${rows}</div></div>`;
}

/* ---------- views ---------- */
function warningsHTML(t){
  return t.warn.length ? `<div class="warnbox"><b>Some data in the tournament file was ignored:</b><ul>${t.warn.map(w => `<li>${w}</li>`).join("")}</ul></div>` : "";
}
function quorumHTML(t){
  const N = t.players.length;
  if(t.drawPending) return `<div class="card" style="margin-top:20px"><div class="card-h"><h2>Waiting for the draw</h2><small>${N} players registered</small></div>
    <div class="card-b"><div class="hint" style="margin-bottom:14px">The quorum is reached. The groups will be drawn at random by the organiser.</div>
    <div class="plist">${t.players.map(p => `<span class="chip">${avatar(p)}${esc(p)}</span>`).join("")}</div></div></div>`;
  if(t.tooMany) return `<div class="card"><div class="card-h"><h2>Too many players</h2></div><div class="card-b hint">${N} players registered. The maximum is ${MAX_PLAYERS}.</div></div>`;
  return `<div class="card" style="margin-top:20px"><div class="card-h"><h2>Waiting for players</h2><small>Registration</small></div>
    <div class="card-b"><div class="hint">The tournament starts when at least <b>${QUORUM}</b> players are registered: ${N} of ${QUORUM} so far, ${QUORUM - N} more needed.</div>
    <div class="qbar"><div style="width:${Math.round(100 * N / QUORUM)}%"></div></div>
    ${N ? `<div class="plist">${t.players.map(p => `<span class="chip">${avatar(p)}${esc(p)}</span>`).join("")}</div>` : ""}</div></div>`;
}
function rankingHTML(t){
  const rows = [];
  t.groups.forEach((g, gi) => { const st = statsFor(g, playedMatches(t, gi)); g.forEach(p => rows.push({p, gi, s:st[p]})); });
  rows.sort((x,y) => cmpStats(x.s, y.s) || t.players[x.p].localeCompare(t.players[y.p]));
  return `<div class="card"><div class="card-h"><h2>Ranking</h2><small>All players · group stage</small></div>
    <div class="tbl-wrap"><table class="st"><thead><tr><th class="pos">#</th><th class="pl">Player</th><th>Group</th>${statHeads}</tr></thead>
    <tbody>${rows.map((r, i) => `<tr><td class="pos">${i+1}</td>${pcell(t, r.p)}<td>${GL(r.gi)}</td>${statCells(r.s)}</tr>`).join("")}</tbody></table></div>
    <div class="note">${statKey}<span>Order: W → SW → Pts</span></div></div>`;
}
function groupCardHTML(t, gi, thirdQ){
  const {order, st} = rankGroup(t, gi), done = groupDone(t, gi);
  const ms = groupMatches(t, gi), played = ms.filter(([a,b]) => lookup(t.gr, a, b)).length;
  const rows = order.map((p, i) => {
    let cls = "";
    if(done) cls = i < 2 ? "q" : (i === 2 && thirdQ.has(p)) ? "q3" : (i === 2 && t.T && !thirdQ.size) ? "" : "out";
    return `<tr class="${cls}"><td class="pos">${i+1}</td>${pcell(t, p)}${statCells(st[p])}</tr>`;
  }).join("");
  const matches = groupRounds(t, gi).map((rd, ri) => rd.map(([a,b]) => matchHTML(t, {a, b, sets:lookup(t.gr, a, b)}, `Round ${ri+1}`, false)).join("")).join("");
  return `<div class="card"><div class="card-h"><h2>Group ${GL(gi)}</h2><small>${done ? "Complete" : `${played} of ${ms.length} played`}</small></div>
    <div class="tbl-wrap"><table class="st"><thead><tr><th class="pos"></th><th class="pl">Player</th>${statHeads}</tr></thead><tbody>${rows}</tbody></table></div>
    <div class="rdh">Matches</div>${matches}</div>`;
}
function groupsHTML(t, km){
  const thirdQ = new Set(km.groupsDone && t.T ? thirdsTable(t).slice(0, t.T).map(r => r.pid) : []);
  return `<div class="groups">${t.groups.map((_,gi) => groupCardHTML(t, gi, thirdQ)).join("")}</div>
    <div class="note free"><span><i class="key" style="background:var(--q)"></i>Qualified</span>${t.T ? `<span><i class="key" style="background:var(--q3)"></i>Qualified as best 3rd</span>` : ""}${statKey}
    <span>Order: W → SW → Pts → head-to-head</span><span>Best of ${t.bestOf}</span>${t.drawnAt ? `<span>Groups drawn at random on ${esc(t.drawnAt)}</span>` : ""}</div>`;
}
function thirdsHTML(t, km){
  const rows = thirdsTable(t);
  const body = rows.map((r, i) => `<tr class="${km.groupsDone ? (i < t.T ? "q3" : "out") : ""}"><td class="pos">${i+1}</td>${pcell(t, r.pid)}<td>${GL(r.g)}${r.done ? "" : "*"}</td>${statCells(r.s)}<td>${r.wpm.toFixed(2)}</td><td>${r.swpm.toFixed(2)}</td><td>${r.pwpm.toFixed(1)}</td></tr>`).join("");
  return `<div class="card"><div class="card-h"><h2>Best 3rd-placed players</h2><small>${t.T} of ${rows.length} qualify</small></div>
    <div class="tbl-wrap"><table class="st"><thead><tr><th class="pos">#</th><th class="pl">Player</th><th>Group</th>${statHeads}<th title="Wins per match">W/M</th><th title="Sets won per match">SW/M</th><th title="Points scored per match">Pts/M</th></tr></thead><tbody>${body}</tbody></table></div>
    <div class="note"><span>Compared per match (groups can differ in size): W/M → SW/M → Pts/M</span><span>Qualified 3rds face a winner from another group</span>${rows.some(r => !r.done) ? "<span>* group still in progress</span>" : ""}</div></div>`;
}
function bracketHTML(t, km){
  const card = m => matchHTML(t, m, `M${m.num}`, true);
  const cols = km.rounds.map((r, ri) => {
    const lin = ri > 0 ? "lin" : "";
    let inner = "";
    if(ri === km.rounds.length - 1) inner = `<div class="pair"><div class="slot ${lin}">${card(r.ms[0])}</div></div>`;
    else for(let i=0;i<r.ms.length;i+=2) inner += `<div class="pair j">${[r.ms[i], r.ms[i+1]].map(m => `<div class="slot ${lin}">${card(m)}</div>`).join("")}</div>`;
    return `<div class="round"><h4>${r.name}</h4><div class="rcol">${inner}</div></div>`;
  }).join("");
  const champ = `<div class="champ"><div class="trophy">🏆</div><div class="cl">Champion</div><div class="cn">${km.champion!=null ? esc(t.players[km.champion]) : "To be decided"}</div>
    ${km.third ? `<div class="tpbox"><h5>3rd place</h5>${card(km.third)}</div>` : ""}</div>`;
  const podium = km.champion!=null ? `<div class="podium"><span>🥇 ${esc(t.players[km.champion])}</span><span>🥈 ${esc(t.players[km.runnerUp])}</span>${km.thirdPlace!=null ? `<span>🥉 ${esc(t.players[km.thirdPlace])}</span>` : ""}</div>` : `<small>${km.groupsDone ? "" : "Fills in when every group is complete"}</small>`;
  return `<div class="card"><div class="card-h"><h2>Knockout stage</h2>${podium}</div><div class="bwrap"><div class="bracket">${cols}${champ}</div></div></div>`;
}
function tournamentHTML(t, tab){
  let html = warningsHTML(t);
  if(!t.quorum) return {html: html + quorumHTML(t), tab, phase: t.drawPending ? "Waiting for the draw" : "Registration"};
  const km = koModel(t), ph = phaseOf(t, km);
  if(!tab) tab = ph.key === "groups" ? "groups" : "ko";
  if(tab === "thirds" && !t.T) tab = "groups";
  const tabs = [["groups","Groups"], ["ranking","Ranking"]];
  if(t.T) tabs.push(["thirds","Best 3rds"]);
  tabs.push(["ko","Knockout"]);
  html += stepsHTML(km, ph)
    + `<div class="tabs" role="tablist">${tabs.map(([k,l]) => `<button class="tab ${tab===k?"on":""}" role="tab" aria-selected="${tab===k}" data-tab="${k}">${l}</button>`).join("")}</div>`;
  html += tab === "groups" ? groupsHTML(t, km) : tab === "ranking" ? rankingHTML(t) : tab === "thirds" ? thirdsHTML(t, km) : bracketHTML(t, km);
  return {html, tab, phase: ph.label, km};
}

/* ---------- page boot ---------- */
if(typeof document !== "undefined"){
  const app = document.getElementById("app");
  // URL: tournament.html#<code>[/<tab>] — the fragment is never sent to the server
  const [rawCode = "", rawTab = ""] = decodeURIComponent(location.hash.slice(1)).split("/");
  const code = rawCode.trim().toLowerCase();
  let T = null, tab = ["groups","ranking","thirds","ko"].includes(rawTab) ? rawTab : null;
  const fatal = (title, msg) => {
    document.getElementById("tsub").textContent = "";
    app.innerHTML = `<div class="card" style="margin-top:20px"><div class="card-h"><h2>${esc(title)}</h2></div><div class="card-b"><p class="hint" style="margin-top:0">${esc(msg)}</p><a class="btn pri" href="./">Enter another code</a></div></div>`;
  };
  const render = () => {
    const r = tournamentHTML(T, tab); tab = r.tab; app.innerHTML = r.html;
    document.title = `${T.name} · Table Tennis`;
    document.getElementById("tname").textContent = T.name;
    document.getElementById("tsub").textContent = [T.date, `${T.players.length} player${T.players.length===1?"":"s"}`, `Best of ${T.bestOf}`, r.phase || "Registration"].filter(Boolean).join(" · ");
  };
  const load = async () => {
    if(!CODE_RE.test(code)) return fatal("Invalid tournament code", "A tournament code is exactly 32 characters (letters a–z and digits 0–9).");
    let data;
    try{
      data = await Vault.load(code);
      if(data === null) return fatal("Tournament not found", "No tournament exists with this code. Check the code and try again.");
    }catch(e){ return fatal("Could not load the tournament", `The tournament file could not be read (${e.message}).`); }
    T = build(data); render();
  };
  document.addEventListener("click", e => { const b = e.target.closest("[data-tab]"); if(b && T){ tab = b.dataset.tab; history.replaceState(null, "", `#${code}/${tab}`); render(); } });
  document.getElementById("refresh").addEventListener("click", load);
  window.addEventListener("hashchange", () => location.reload());   // a different code was typed into the URL
  load();
}
if(typeof module !== "undefined") module.exports = {build, koModel, phaseOf, tournamentHTML, rankGroup, thirdsTable, formats};
