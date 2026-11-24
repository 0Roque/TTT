#!/usr/bin/env python3
"""Offline tournament manager (GUI).

Add players, lock the groups, enter group and knockout results, then publish
(encrypt into data/, commit and push). Every change is saved immediately to the
private file tournaments/<code>.json.

Run:  python3 tools/manager.py

The group/bracket logic below mirrors assets/tournament.js so the matches shown
here are exactly the ones shown on the website.
"""
import json, math, os, re, secrets, subprocess, sys
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ttt  # noqa: E402

QUORUM, MAX_PLAYERS = 6, 40
ROUND_NAME = {2: "Final", 4: "Semi-finals", 8: "Quarter-finals", 16: "Round of 16"}
ROUND_ONE = {2: "Final", 4: "Semi-final", 8: "Quarter-final", 16: "Round of 16"}
GL = lambda i: chr(65 + i)


# ───────────────────────── tournament logic (mirror of tournament.js) ─────────────────────────
def ko_size(G): return 2 if G == 1 else 2 ** math.ceil(math.log2(2 * G))
def thirds_needed(G): return 0 if G == 1 else ko_size(G) - 2 * G


def formats(N):
    out = []
    for G in (1, 2, 3, 4, 6, 7, 8):
        if G < math.ceil(N / 5) or G > N // 3:
            continue
        K, T = ko_size(G), thirds_needed(G)
        if T > G:
            continue
        base, ex = divmod(N, G)
        out.append({"G": G, "K": K, "T": T, "sizes": [base + (1 if i < ex else 0) for i in range(G)]})
    return out


def recommended(N):
    """Default format: 6-9 players play 2 groups and semi-finals; otherwise the longest knockout possible,
    then about 4 players per group (on a tie, more groups)."""
    fm = formats(N)
    if N <= 9:
        return next(f for f in fm if f["K"] == 4)
    return min(fm, key=lambda f: (-f["K"], abs(f["G"] - N / 4), -f["G"]))


def format_label(f, rec=False):
    q = "top 2" + (f" + {f['T']} best 3rds" if f["T"] else "")
    return f"{f['G']} group{'s' if f['G'] > 1 else ''} ({'-'.join(map(str, f['sizes']))}) · {q} → {ROUND_NAME[f['K']]}" + ("  ★ recommended" if rec else "")


def ballot(n, sizes):
    """Completely random draw, like pulling balls from a pot.

    The players are shuffled with the operating system's cryptographic random generator (the order of the
    player list has no influence), then each ball drawn goes to the next group in turn (A, B, C, A, B, C…),
    skipping groups that are already full. Returns (groups, draw order).
    """
    order = list(range(n))
    secrets.SystemRandom().shuffle(order)
    groups, g = [[] for _ in sizes], 0
    for p in order:
        while len(groups[g]) >= sizes[g]:
            g = (g + 1) % len(sizes)
        groups[g].append(p)
        g = (g + 1) % len(sizes)
    return groups, order


def rr(ps):
    a = list(ps)
    if len(a) % 2:
        a.append(None)
    n, rounds = len(a), []
    for r in range(n - 1):
        m = []
        for i in range(n // 2):
            x, y = a[i], a[n - 1 - i]
            if x is not None and y is not None:
                m.append((y, x) if r % 2 else (x, y))
        rounds.append(m)
        a.insert(1, a.pop())
    return rounds


def summ(sets):
    a = b = pa = pb = 0
    for x, y in sets:
        if x > y: a += 1
        else: b += 1
        pa += x; pb += y
    return a, b, pa, pb


def valid_set(x, y):
    if x < 0 or y < 0: return False
    hi, lo = max(x, y), min(x, y)
    if hi < 11: return False
    if hi == 11: return lo <= 9
    return hi - lo == 2


def parse_set(s):
    if isinstance(s, str):
        m = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", s)
        return (int(m[1]), int(m[2])) if m else None
    if isinstance(s, (list, tuple)) and len(s) == 2 and all(isinstance(v, int) for v in s):
        return (s[0], s[1])
    return None


def check_sets(sets, best_of):
    """Returns an error message, or None when the sets form a valid, finished match."""
    if not sets:
        return "Enter at least one set."
    need, wa, wb = (best_of + 1) // 2, 0, 0
    for i, (x, y) in enumerate(sets):
        if not valid_set(x, y):
            return f"Set {i + 1} ({x}-{y}) is not a valid score: first to 11, win by 2 (e.g. 11-9, 12-10)."
        if need in (wa, wb):
            return f"The match was already decided before set {i + 1}."
        if x > y: wa += 1
        else: wb += 1
    if wa < need and wb < need:
        return f"Match not finished: a player needs {need} sets to win (currently {wa}-{wb})."
    return None


def pkey(a, b): return (a, b) if a < b else (b, a)


def meet(a, b):
    k = 1
    while a != b:
        a >>= 1; b >>= 1; k += 1
    return k


def arrange(pairs):
    M = len(pairs)
    if M <= 2:
        return pairs
    R = int(math.log2(M)) + 1

    def cost(order):
        c, toks = 0, []
        for slot, pi in enumerate(order):
            for t in pairs[pi]:
                toks.append((t, slot))
        for i in range(len(toks)):
            for j in range(i + 1, len(toks)):
                (a, sa), (b, sb) = toks[i], toks[j]
                if sa == sb: continue
                w = R - meet(sa, sb) + 1
                if a["t"] != "3" and b["t"] != "3" and a["g"] == b["g"]: c += 100 * w * w
                if a["t"] == "W" and b["t"] == "W": c += w * w
        return c

    best, bc = None, math.inf
    used, cur = [False] * M, [0]
    used[0] = True

    def rec():
        nonlocal best, bc
        if len(cur) == M:
            c = cost(cur)
            if c < bc: bc, best = c, list(cur)
            return
        for i in range(1, M):
            if used[i]: continue
            used[i] = True; cur.append(i); rec(); cur.pop(); used[i] = False
    rec()
    return [pairs[i] for i in best]


def build_pairs(G, T):
    if G == 1:
        return [[{"t": "W", "g": 0}, {"t": "R", "g": 0}]]
    pairs = [[{"t": "W", "g": i}, {"t": "3", "s": i, "vs": i}] for i in range(T)]
    avail = list(range(G))
    for i in range(T, G):
        x = i ^ 1
        p = x if (x < G and x != i and x in avail) else next(v for v in avail if v != i)
        avail.remove(p)
        pairs.append([{"t": "W", "g": i}, {"t": "R", "g": p}])
    for j in range(0, len(avail), 2):
        pairs.append([{"t": "R", "g": avail[j]}, {"t": "R", "g": avail[j + 1]}])
    return arrange(pairs)


class Model:
    """Read-only view of a tournament dict, computed exactly like the website."""

    def __init__(self, d):
        self.d = d
        self.best_of = d.get("bestOf") if d.get("bestOf") in (3, 5, 7) else 5
        self.players, self.idx = [], {}
        for raw in d.get("players") or []:
            nm = str(raw if raw is not None else "").strip()
            if nm and nm.lower() not in self.idx:
                self.idx[nm.lower()] = len(self.players); self.players.append(nm)
        N = len(self.players)
        self.quorum = QUORUM <= N <= MAX_PLAYERS
        self.locked = self.drawn = False      # "drawn": the random draw has been made (groups are fixed)
        self.groups = None
        if not self.quorum:
            return
        g = self._custom_groups(d.get("groups"))
        if not g:
            return                            # quorum reached, waiting for the draw
        self.groups, self.locked = g, True
        self.drawn = True
        self.G = len(self.groups); self.K = ko_size(self.G); self.T = thirds_needed(self.G)
        self.pairs = build_pairs(self.G, self.T)
        self.group_of = {p: gi for gi, grp in enumerate(self.groups) for p in grp}
        self.gr, self.kr = {}, {}
        for e in d.get("groupResults") or []:
            m = self._parse(e)
            if m and self.group_of[m[0]] == self.group_of[m[1]] and pkey(m[0], m[1]) not in self.gr:
                self.gr[pkey(m[0], m[1])] = m
        for e in d.get("knockoutResults") or []:
            m = self._parse(e)
            if m and pkey(m[0], m[1]) not in self.kr:
                self.kr[pkey(m[0], m[1])] = m
        self.schedule = self._schedule(d.get("matchOrder"))

    def default_schedule(self):
        """Round 1 of every group, then round 2 of every group, and so on: (group, round, a, b)."""
        rounds = [self.group_rounds(gi) for gi in range(self.G)]
        return [(gi, r, a, b) for r in range(max(map(len, rounds))) for gi in range(self.G)
                if r < len(rounds[gi]) for a, b in rounds[gi][r]]

    def _schedule(self, order):
        """Play order of all group matches: the pairs listed in "matchOrder" first, then any others in default order."""
        base = self.default_schedule()
        by_key, seen, out = {pkey(x[2], x[3]): x for x in base}, set(), []
        for e in order if isinstance(order, list) else []:
            if not isinstance(e, list) or len(e) != 2: continue
            a, b = (self.idx.get(str(v).strip().lower()) for v in e)
            k = pkey(a, b) if a is not None and b is not None else None
            if k in by_key and k not in seen:
                seen.add(k); out.append(by_key[k])
        return out + [x for x in base if pkey(x[2], x[3]) not in seen]

    def _custom_groups(self, groups):
        if not isinstance(groups, list) or not groups:
            return None
        seen, out = set(), []
        for grp in groups:
            ids = []
            for nm in grp if isinstance(grp, list) else []:
                i = self.idx.get(str(nm).strip().lower())
                if i is None or i in seen: return None
                seen.add(i); ids.append(i)
            out.append(ids)
        if len(seen) != len(self.players) or any(len(x) < 3 for x in out) or len(out) > 8 or thirds_needed(len(out)) > len(out):
            return None
        return out

    def _parse(self, e):
        if not isinstance(e, dict): return None
        a, b = self.idx.get(str(e.get("a", "")).strip().lower()), self.idx.get(str(e.get("b", "")).strip().lower())
        if a is None or b is None or a == b or not isinstance(e.get("sets"), list): return None
        sets = [parse_set(s) for s in e["sets"]]
        if any(s is None for s in sets) or check_sets(sets, self.best_of): return None
        return (a, b, sets)

    @staticmethod
    def lookup(table, a, b):
        r = table.get(pkey(a, b))
        if not r: return None
        return r[2] if r[0] == a else [(y, x) for x, y in r[2]]

    def group_rounds(self, gi): return rr(self.groups[gi])
    def group_matches(self, gi): return [m for rd in self.group_rounds(gi) for m in rd]
    def played(self, gi): return [(a, b, s) for a, b in self.group_matches(gi) if (s := self.lookup(self.gr, a, b))]
    def group_done(self, gi): return all(self.lookup(self.gr, a, b) for a, b in self.group_matches(gi))

    @staticmethod
    def stats_for(ps, ms):
        st = {p: dict(p=0, w=0, l=0, sw=0, sl=0, pw=0, pl=0) for p in ps}
        for a, b, sets in ms:
            if a not in st or b not in st: continue
            sa, sb, pa, pb = summ(sets); A, B = st[a], st[b]
            A["p"] += 1; B["p"] += 1; A["sw"] += sa; A["sl"] += sb; B["sw"] += sb; B["sl"] += sa
            A["pw"] += pa; A["pl"] += pb; B["pw"] += pb; B["pl"] += pa
            if sa > sb: A["w"] += 1; B["l"] += 1
            else: B["w"] += 1; A["l"] += 1
        return st

    def rank_group(self, gi):
        ps = self.groups[gi]; st = self.stats_for(ps, self.played(gi))
        key = lambda x: (st[x]["w"], st[x]["sw"], st[x]["pw"])
        order = sorted(ps, key=lambda x: (-st[x]["w"], -st[x]["sw"], -st[x]["pw"], ps.index(x)))
        for i in range(len(order) - 1):
            x, y = order[i], order[i + 1]
            if key(x) != key(y): continue
            if i > 0 and key(order[i - 1]) == key(x): continue
            if i + 2 < len(order) and key(y) == key(order[i + 2]): continue
            h = self.lookup(self.gr, x, y)
            if h:
                sa, sb, _, _ = summ(h)
                if sb > sa: order[i], order[i + 1] = y, x
        return order, st

    def thirds_table(self):
        rows = []
        for gi, g in enumerate(self.groups):
            if len(g) < 3: continue
            order, st = self.rank_group(gi); pid = order[2]; s = st[pid]
            per = lambda v: v / s["p"] if s["p"] else 0
            rows.append(dict(g=gi, pid=pid, s=s, done=self.group_done(gi), wpm=per(s["w"]), swpm=per(s["sw"]), pwpm=per(s["pw"])))
        rows.sort(key=lambda r: (-r["wpm"], -r["swpm"], -r["pwpm"], r["g"]))
        return rows

    def assign_thirds(self):
        q = self.thirds_table()[: self.T]
        slots = [(tok, p[1 - ti]) for p in self.pairs for ti, tok in enumerate(p) if tok["t"] == "3"]
        res, used = [None] * len(slots), [False] * len(q)

        def bt(i):
            if i == len(slots): return True
            for j in range(len(q)):
                if used[j] or q[j]["g"] == slots[i][1].get("g"): continue
                used[j] = True; res[i] = q[j]
                if bt(i + 1): return True
                used[j] = False
            return False
        bt(0)
        return {slots[i][0]["s"]: res[i]["pid"] for i in range(len(slots)) if res[i]}

    def ko_model(self):
        done = all(self.group_done(gi) for gi in range(self.G))
        ranks = [self.rank_group(gi)[0] if self.group_done(gi) else None for gi in range(self.G)]
        tmap = self.assign_thirds() if done and self.T else {}

        def res(tok):
            if tok["t"] == "W": return ranks[tok["g"]][0] if ranks[tok["g"]] else None
            if tok["t"] == "R": return ranks[tok["g"]][1] if ranks[tok["g"]] else None
            return tmap.get(tok["s"])

        def lab(tok):
            if tok["t"] == "W": return f"Winner Group {GL(tok['g'])}"
            if tok["t"] == "R": return f"Runner-up Group {GL(tok['g'])}"
            others = [GL(i) for i in range(self.G) if i != tok["vs"]]
            return f"Best 3rd {'/'.join(others)}" if len(others) <= 4 else f"Best 3rd (not {GL(tok['vs'])})"

        num = 0

        def mk(a, b, la, lb, stage):
            nonlocal num
            num += 1
            return dict(num=num, a=a, b=b, la=la, lb=lb, stage=stage,
                        sets=self.lookup(self.kr, a, b) if a is not None and b is not None else None)

        def winner(m):
            if not m["sets"]: return None
            sa, sb, _, _ = summ(m["sets"]); return m["a"] if sa > sb else m["b"]

        def loser(m):
            if not m["sets"]: return None
            sa, sb, _, _ = summ(m["sets"]); return m["b"] if sa > sb else m["a"]

        size = self.K
        prev = [mk(res(p[0]), res(p[1]), lab(p[0]), lab(p[1]), ROUND_ONE[size]) for p in self.pairs]
        rounds, third = [(ROUND_NAME[size], prev)], None
        while len(prev) > 1:
            size //= 2
            cur = [mk(winner(prev[i]), winner(prev[i + 1]), f"Winner M{prev[i]['num']}", f"Winner M{prev[i + 1]['num']}", ROUND_ONE[size])
                   for i in range(0, len(prev), 2)]
            if size == 2:
                third = mk(loser(prev[0]), loser(prev[1]), f"Loser M{prev[0]['num']}", f"Loser M{prev[1]['num']}", "3rd place")
            rounds.append((ROUND_NAME[size], cur)); prev = cur
        return dict(rounds=rounds, third=third, champion=winner(prev[0]), groups_done=done)


# ───────────────────────── GUI ─────────────────────────
MUTED, ERR = "#5f6368", "#c5221f"


def git(*args, timeout=90):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never hang waiting for a password prompt
    return subprocess.run(["git", "-C", str(ttt.ROOT), *args], capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=env)


def pages_url():
    try:
        url = git("remote", "get-url", "origin", timeout=10).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", url)
        return f"https://{m[1].lower()}.github.io/{m[2]}/" if m else ""
    except Exception:
        return ""


class ScoreDialog(tk.Toplevel):
    """Modal dialog to enter the set scores of one match. self.result = list of (a, b) sets, [] to clear, or None."""

    def __init__(self, parent, title, name_a, name_b, best_of, sets=None):
        super().__init__(parent)
        self.title(title); self.transient(parent); self.resizable(False, False)
        self.best_of, self.result = best_of, None
        f = ttk.Frame(self, padding=18); f.pack(fill="both", expand=True)
        ttk.Label(f, text=title, style="H.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=f"Best of {best_of} · sets to 11, win by 2 · leave unplayed sets empty", foreground=MUTED).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
        for c, nm in ((1, name_a), (2, name_b)):
            ttk.Label(f, text=nm, style="B.TLabel", anchor="center", width=18).grid(row=2, column=c, padx=4, pady=(0, 4))
        self.cells = []
        for i in range(best_of):
            ttk.Label(f, text=f"Set {i + 1}", foreground=MUTED).grid(row=3 + i, column=0, sticky="w", padx=(0, 10))
            row = []
            for c in (1, 2):
                e = ttk.Entry(f, width=6, justify="center", font=("TkDefaultFont", 12))
                e.grid(row=3 + i, column=c, pady=3)
                if sets and i < len(sets): e.insert(0, str(sets[i][c - 1]))
                e.bind("<KeyRelease>", lambda _e: self.update_tally())
                row.append(e)
            self.cells.append(row)
        r = 3 + best_of
        self.tally = ttk.Label(f, text="", style="T.TLabel"); self.tally.grid(row=r, column=1, columnspan=2, pady=(10, 0))
        self.err = ttk.Label(f, text="", foreground=ERR, wraplength=360); self.err.grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        bf = ttk.Frame(f); bf.grid(row=r + 2, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        if sets: ttk.Button(bf, text="Delete result", command=self.clear).pack(side="left")
        ttk.Button(bf, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self.save()); self.bind("<Escape>", lambda _e: self.destroy())
        self.update_tally()
        self.cells[0][0].focus_set()
        self.wait_visibility(); self.grab_set(); self.wait_window()

    def read(self):
        sets, gap = [], False
        for i, (ea, eb) in enumerate(self.cells):
            xa, xb = ea.get().strip(), eb.get().strip()
            if not xa and not xb: gap = True; continue
            if gap: return sets, f"Set {i + 1} is filled in but an earlier set is empty."
            if not xa or not xb: return sets, f"Set {i + 1} needs both scores."
            if not (xa.isdigit() and xb.isdigit()): return sets, f"Set {i + 1}: scores must be whole numbers."
            sets.append((int(xa), int(xb)))
        return sets, check_sets(sets, self.best_of)

    def update_tally(self):
        sets, _ = self.read()
        sa, sb, _, _ = summ([s for s in sets if valid_set(*s)])
        self.tally.config(text=f"{sa} – {sb}" if sets else ""); self.err.config(text="")

    def save(self):
        sets, err = self.read()
        if err: self.err.config(text=err); return
        self.result = sets; self.destroy()

    def clear(self):
        if messagebox.askyesno("Delete result", "Delete this result?", parent=self):
            self.result = []; self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Table Tennis Tournament Manager"); self.geometry("1040x700"); self.minsize(860, 560)
        self.code = self.d = self.m = None
        self.mtime = 0
        ttt.ensure_hook()  # git refuses commits containing readable tournament data
        self._style()
        self._build()
        self.reload_list()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<FocusIn>", self.on_focus)

    # ── look ──
    def _style(self):
        s = ttk.Style(self)
        if "clam" in s.theme_names(): s.theme_use("clam")
        base = ("TkDefaultFont", 10)
        s.configure("H.TLabel", font=("TkDefaultFont", 14, "bold"))
        s.configure("B.TLabel", font=("TkDefaultFont", 10, "bold"))
        s.configure("T.TLabel", font=("TkDefaultFont", 18, "bold"))
        s.configure("Muted.TLabel", foreground=MUTED)
        s.configure("Accent.TButton", foreground="white", background="#1a73e8", font=base)
        s.map("Accent.TButton", background=[("active", "#1765cc"), ("disabled", "#a8c7fa")])
        s.configure("Treeview", rowheight=26, font=base)
        s.configure("Treeview.Heading", font=("TkDefaultFont", 10, "bold"))
        s.configure("TNotebook.Tab", padding=(14, 6))

    # ── layout ──
    def _build(self):
        top = ttk.Frame(self, padding=(12, 10)); top.pack(fill="x")
        ttk.Label(top, text="Tournament:").pack(side="left")
        self.pick = ttk.Combobox(top, state="readonly", width=48); self.pick.pack(side="left", padx=6)
        self.pick.bind("<<ComboboxSelected>>", lambda _e: self.open(self.codes[self.pick.current()]))
        ttk.Button(top, text="New…", command=self.new).pack(side="left")
        ttk.Button(top, text="Delete…", command=self.delete).pack(side="left", padx=6)
        self.pub_btn = ttk.Button(top, text="Publish", style="Accent.TButton", command=self.publish); self.pub_btn.pack(side="right")
        self.status = ttk.Label(top, text="", style="Muted.TLabel"); self.status.pack(side="right", padx=10)

        self.nb = ttk.Notebook(self); self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.tab_details = ttk.Frame(self.nb, padding=16); self.nb.add(self.tab_details, text="Details")
        self.tab_players = ttk.Frame(self.nb, padding=16); self.nb.add(self.tab_players, text="Players & groups")
        self.tab_groups = ttk.Frame(self.nb, padding=16); self.nb.add(self.tab_groups, text="Group matches")
        self.tab_ko = ttk.Frame(self.nb, padding=16); self.nb.add(self.tab_ko, text="Knockout")
        self.tab_stand = ttk.Frame(self.nb, padding=16); self.nb.add(self.tab_stand, text="Standings")
        self._build_details(); self._build_players(); self._build_groups(); self._build_ko(); self._build_standings()

    def _build_details(self):
        f = self.tab_details
        self.v_name, self.v_date, self.v_best = tk.StringVar(), tk.StringVar(), tk.StringVar()
        rows = [("Name", ttk.Entry(f, textvariable=self.v_name, width=44)),
                ("Date (DD/MM/YYYY)", ttk.Entry(f, textvariable=self.v_date, width=14)),
                ("Best of", ttk.Combobox(f, textvariable=self.v_best, values=("3", "5", "7"), state="readonly", width=5))]
        for i, (lbl, w) in enumerate(rows):
            ttk.Label(f, text=lbl).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 12)); w.grid(row=i, column=1, sticky="w")
        self.best_box = rows[2][1]
        ttk.Button(f, text="Save details", style="Accent.TButton", command=self.save_details).grid(row=3, column=1, sticky="w", pady=(10, 20))
        ttk.Separator(f).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="Tournament code").grid(row=5, column=0, sticky="w", pady=5)
        self.v_code = tk.StringVar(); ttk.Entry(f, textvariable=self.v_code, state="readonly", width=40, font=("TkFixedFont", 10)).grid(row=5, column=1, sticky="w")
        ttk.Button(f, text="Copy code", command=lambda: self.copy(self.code)).grid(row=5, column=2, padx=6)
        ttk.Label(f, text="Share link").grid(row=6, column=0, sticky="w", pady=5)
        self.v_link = tk.StringVar(); ttk.Entry(f, textvariable=self.v_link, state="readonly", width=70).grid(row=6, column=1, sticky="w")
        ttk.Button(f, text="Copy link", command=lambda: self.copy(self.v_link.get())).grid(row=6, column=2, padx=6)
        ttk.Label(f, text="Keep the code private: anyone who has it can view this tournament.", style="Muted.TLabel").grid(row=7, column=1, sticky="w", pady=(4, 0))

    def _build_players(self):
        f = self.tab_players; f.columnconfigure(1, weight=1); f.rowconfigure(2, weight=1)
        left = ttk.Frame(f); left.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 20))
        ttk.Label(left, text="Players", style="B.TLabel").pack(anchor="w")
        self.quorum_lbl = ttk.Label(left, text="", style="Muted.TLabel"); self.quorum_lbl.pack(anchor="w", pady=(2, 8))
        add = ttk.Frame(left); add.pack(fill="x")
        self.v_new = tk.StringVar()
        self.new_entry = ttk.Entry(add, textvariable=self.v_new, width=26); self.new_entry.pack(side="left", fill="x", expand=True)
        self.new_entry.bind("<Return>", lambda _e: self.add_player())
        self.add_btn = ttk.Button(add, text="Add", command=self.add_player); self.add_btn.pack(side="left", padx=(6, 0))
        lf = ttk.Frame(left); lf.pack(fill="both", expand=True, pady=8)
        self.plist = tk.Listbox(lf, height=18, width=34, activestyle="none", font=("TkDefaultFont", 11), selectbackground="#1a73e8")
        sb = ttk.Scrollbar(lf, command=self.plist.yview); self.plist.config(yscrollcommand=sb.set)
        self.plist.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
        self.plist.bind("<Double-Button-1>", lambda _e: self.rename_player())
        bf = ttk.Frame(left); bf.pack(fill="x")
        self.p_btns = [ttk.Button(bf, text="Add many…", command=self.add_many),
                       ttk.Button(bf, text="Remove", command=self.remove_player)]
        for b in self.p_btns: b.pack(side="left", padx=(0, 4))
        ttk.Button(bf, text="Rename…", command=self.rename_player).pack(side="left")

        ttk.Label(f, text="Group draw", style="B.TLabel").grid(row=0, column=1, sticky="w")
        gf = ttk.Frame(f); gf.grid(row=1, column=1, sticky="ew", pady=(4, 8)); gf.columnconfigure(1, weight=1)
        self.v_fmt = tk.StringVar()
        ttk.Label(gf, text="Format:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        # small base width + sticky "ew": the box shrinks on narrow or high-DPI screens instead of pushing the button out
        self.fmt_box = ttk.Combobox(gf, textvariable=self.v_fmt, state="readonly", width=20); self.fmt_box.grid(row=0, column=1, sticky="ew")
        self.fmt_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_groups_preview())
        # own row, so it is always visible whatever the window size
        self.lock_btn = ttk.Button(gf, text="🎲 Draw groups", style="Accent.TButton", command=self.toggle_lock)
        self.lock_btn.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0), ipadx=10, ipady=3)
        self.groups_txt = tk.Text(f, height=20, wrap="word", font=("TkFixedFont", 10), relief="flat", background="#f8f9fa", padx=12, pady=10)
        self.groups_txt.grid(row=2, column=1, sticky="nsew")

    def _tree(self, parent, cols, widths):
        fr = ttk.Frame(parent); fr.pack(fill="both", expand=True)
        tv = ttk.Treeview(fr, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, widths):
            tv.heading(c, text=c); tv.column(c, width=w, anchor="w" if c in ("Player A", "Player B", "Sets") else "center", stretch=c == "Sets")
        sb = ttk.Scrollbar(fr, command=tv.yview); tv.config(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
        tv.tag_configure("done", foreground=MUTED); tv.tag_configure("todo", foreground="#202124"); tv.tag_configure("wait", foreground="#9aa0a6")
        return tv

    def _build_groups(self):
        f = self.tab_groups
        bar = ttk.Frame(f); bar.pack(fill="x", pady=(0, 8))
        self.g_info = ttk.Label(bar, text="", style="Muted.TLabel"); self.g_info.pack(side="left")
        self.v_gfilter = tk.StringVar(value="All")
        ttk.Combobox(bar, textvariable=self.v_gfilter, values=("All", "To play", "Played"), state="readonly", width=9).pack(side="right")
        ttk.Label(bar, text="Show:").pack(side="right", padx=4)
        self.v_gfilter.trace_add("write", lambda *_: self.refresh_group_matches())
        ttk.Button(bar, text="Enter / edit result…", style="Accent.TButton", command=self.edit_group_result).pack(side="right", padx=10)
        obar = ttk.Frame(f); obar.pack(fill="x", pady=(0, 8))
        ttk.Label(obar, text="Play order:").pack(side="left")
        ttk.Button(obar, text="▲ Earlier", command=lambda: self.shift_match(-1)).pack(side="left", padx=(6, 0))
        ttk.Button(obar, text="▼ Later", command=lambda: self.shift_match(1)).pack(side="left", padx=4)
        ttk.Button(obar, text="Move to #…", command=self.move_match_to).pack(side="left")
        ttk.Button(obar, text="Reset order…", command=self.reset_order).pack(side="left", padx=4)
        ttk.Label(obar, text="or drag a match · Alt+↑/↓", style="Muted.TLabel").pack(side="left", padx=8)
        self.gtree = self._tree(f, ("#", "Group", "Round", "Player A", "Score", "Player B", "Sets"), (45, 60, 60, 200, 70, 200, 240))
        self.gtree.tag_configure("b2b", foreground="#e37400")
        self.gtree.bind("<Double-1>", lambda _e: self.edit_group_result())
        self.gtree.bind("<Return>", lambda _e: self.edit_group_result())
        self.gtree.bind("<Alt-Up>", lambda _e: (self.shift_match(-1), "break")[1])
        self.gtree.bind("<Alt-Down>", lambda _e: (self.shift_match(1), "break")[1])
        self.gtree.bind("<ButtonPress-1>", self.drag_start, add="+")
        self.gtree.bind("<B1-Motion>", self.drag_motion, add="+")
        self.gtree.bind("<ButtonRelease-1>", self.drag_end, add="+")
        self.drag = None

    def _build_ko(self):
        f = self.tab_ko
        bar = ttk.Frame(f); bar.pack(fill="x", pady=(0, 8))
        self.k_info = ttk.Label(bar, text="", style="Muted.TLabel"); self.k_info.pack(side="left")
        ttk.Button(bar, text="Enter result…", style="Accent.TButton", command=self.edit_ko_result).pack(side="right")
        self.ktree = self._tree(f, ("Match", "Stage", "Player A", "Score", "Player B", "Sets"), (60, 110, 200, 70, 200, 230))
        self.ktree.bind("<Double-1>", lambda _e: self.edit_ko_result())
        self.ktree.bind("<Return>", lambda _e: self.edit_ko_result())

    def _build_standings(self):
        self.stand_txt = tk.Text(self.tab_stand, wrap="none", font=("TkFixedFont", 10), relief="flat", background="#f8f9fa", padx=12, pady=10)
        self.stand_txt.pack(fill="both", expand=True)

    # ── files ──
    def path(self, code=None): return ttt.SRC / f"{code or self.code}.json"

    def reload_list(self, select=None):
        ttt.SRC.mkdir(exist_ok=True)
        items = []
        for p in sorted(ttt.SRC.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not ttt.CODE_RE.match(p.stem): continue
            try: name = json.loads(p.read_text(encoding="utf-8")).get("name", "?")
            except Exception: name = "(invalid JSON)"
            items.append((p.stem, f"{name}   ·   {p.stem[:6]}…"))
        self.codes = [c for c, _ in items]
        self.pick["values"] = [lbl for _, lbl in items]
        if not items:
            self.code = None; self.d = None; self.m = None; self.pick.set(""); self.refresh(); return
        code = select if select in self.codes else (self.code if self.code in self.codes else self.codes[0])
        self.pick.current(self.codes.index(code)); self.open(code)

    def open(self, code):
        try:
            self.d = json.loads(self.path(code).read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("Cannot open", f"tournaments/{code}.json is not valid JSON:\n{e}"); return
        self.code = code; self.mtime = self.path().stat().st_mtime
        self.d.setdefault("players", []); self.d.setdefault("groupResults", []); self.d.setdefault("knockoutResults", [])
        self.m = Model(self.d)
        self.refresh()

    def save(self):
        self.path().write_text(json.dumps(self.d, indent=2, ensure_ascii=False) + "\n")
        self.mtime = self.path().stat().st_mtime
        self.m = Model(self.d)
        self.refresh()

    def on_focus(self, _e=None):
        # pick up edits made to the JSON file outside the app
        if self.code and self.path().exists() and self.path().stat().st_mtime != self.mtime:
            self.open(self.code)

    # ── tournaments ──
    def new(self):
        name = simpledialog.askstring("New tournament", "Tournament name:", parent=self)
        if not name or not name.strip(): return
        code = ttt.create_tournament(name.strip(), 5)
        self.reload_list(select=code); self.nb.select(self.tab_details)
        messagebox.showinfo("Tournament created", f"Tournament code:\n\n{code}\n\nAdd players in the “Players & groups” tab, then press Publish.")

    def delete(self):
        if not self.code: return
        name = self.d.get("name", "")
        if not messagebox.askyesno("Delete tournament", f"Delete “{name}” ({self.code[:6]}…)?\n\nIts private file and its encrypted copy in data/ are removed. "
                                   "Press Publish afterwards to remove it from the website.\n\nThis cannot be undone.", icon="warning"):
            return
        self.path().unlink(missing_ok=True)
        (ttt.OUT / f"{ttt.file_id(self.code)}.json").unlink(missing_ok=True)
        self.code = None; self.reload_list()

    def save_details(self):
        name, dt, best = self.v_name.get().strip(), self.v_date.get().strip(), int(self.v_best.get() or 5)
        if not name: messagebox.showerror("Details", "The name cannot be empty."); return
        if dt:
            try: datetime.strptime(dt, "%d/%m/%Y")
            except ValueError: messagebox.showerror("Details", "Use the date format DD/MM/YYYY, e.g. 22/11/2026."); return
        has_results = bool(self.d["groupResults"] or self.d["knockoutResults"])
        if best != self.m.best_of and has_results:
            messagebox.showerror("Details", "“Best of” cannot change once results have been entered."); return
        self.d.update(name=name, date=dt, bestOf=best)
        self.save(); self.reload_list(select=self.code)
        self.status.config(text="Details saved")

    def copy(self, text):
        if text: self.clipboard_clear(); self.clipboard_append(text); self.status.config(text="Copied to clipboard")

    # ── players ──
    def selected_player(self):
        sel = self.plist.curselection()
        return sel[0] if sel else None

    def guard_locked(self):
        if self.m and self.m.locked:
            messagebox.showinfo("Groups drawn", "The groups have been drawn, so the player list can't change.\n\n"
                                "To change players, undo the draw first (this deletes all results). Renaming is always allowed.")
            return True
        return False

    def add_names(self, names):
        if self.guard_locked(): return
        known = {p.lower() for p in self.d["players"]}
        added, skipped = 0, []
        for nm in names:
            nm = " ".join(nm.split())
            if not nm: continue
            if nm.lower() in known: skipped.append(nm); continue
            if len(self.d["players"]) >= MAX_PLAYERS: skipped.append(nm); continue
            self.d["players"].append(nm); known.add(nm.lower()); added += 1
        if added: self.save()
        if skipped: messagebox.showwarning("Players", "Not added (duplicate name or 40-player limit):\n" + "\n".join(skipped))

    def add_player(self):
        self.add_names([self.v_new.get()]); self.v_new.set(""); self.new_entry.focus_set()

    def add_many(self):
        if self.guard_locked(): return
        dlg = tk.Toplevel(self); dlg.title("Add players"); dlg.transient(self)
        ttk.Label(dlg, text="One name per line:", padding=(12, 10, 12, 4)).pack(anchor="w")
        txt = tk.Text(dlg, width=40, height=14, font=("TkDefaultFont", 11)); txt.pack(padx=12, fill="both", expand=True); txt.focus_set()
        bf = ttk.Frame(dlg, padding=12); bf.pack(fill="x")

        def ok():
            names = txt.get("1.0", "end").splitlines(); dlg.destroy(); self.add_names(names)
        ttk.Button(bf, text="Add", style="Accent.TButton", command=ok).pack(side="right")
        ttk.Button(bf, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)
        dlg.wait_visibility(); dlg.grab_set()

    def remove_player(self):
        i = self.selected_player()
        if i is None or self.guard_locked(): return
        nm = self.d["players"][i]
        if messagebox.askyesno("Remove player", f"Remove “{nm}”?"):
            del self.d["players"][i]; self.save()

    def rename_player(self):
        i = self.selected_player()
        if i is None: return
        old = self.d["players"][i]
        new = simpledialog.askstring("Rename player", "New name:", initialvalue=old, parent=self)
        if not new or not new.strip() or new.strip() == old: return
        new = " ".join(new.split())
        if new.lower() in {p.lower() for k, p in enumerate(self.d["players"]) if k != i}:
            messagebox.showerror("Rename", f"There is already a player called “{new}”."); return
        ren = lambda v: new if isinstance(v, str) and v.strip().lower() == old.lower() else v
        self.d["players"][i] = new
        if isinstance(self.d.get("groups"), list): self.d["groups"] = [[ren(v) for v in g] for g in self.d["groups"]]
        for key in ("groupResults", "knockoutResults"):
            for e in self.d[key]: e["a"], e["b"] = ren(e.get("a")), ren(e.get("b"))
        if isinstance(self.d.get("matchOrder"), list): self.d["matchOrder"] = [[ren(v) for v in e] if isinstance(e, list) else e for e in self.d["matchOrder"]]
        self.save(); self.plist.selection_set(i)

    def toggle_lock(self):
        m = self.m
        if not m or not m.quorum or getattr(self, "drawing", False): return
        if m.drawn:
            n = len(self.d["groupResults"]) + len(self.d["knockoutResults"])
            msg = "Undo the draw?\n\nThe groups are removed so players can change and a new draw can be made."
            if n: msg += f"\n\nThis also deletes all {n} result(s)."
            if not messagebox.askyesno("Undo draw", msg, icon="warning"):
                return
            for k in ("groups", "drawnAt", "matchOrder"): self.d.pop(k, None)
            self.d["groupResults"] = []; self.d["knockoutResults"] = []
            self.save(); return
        f = self.chosen_format()
        if not messagebox.askyesno("Draw groups", f"Draw {len(m.players)} players at random into {format_label(f)}?\n\n"
                                   "The draw is final until you undo it."):
            return
        groups, order = ballot(len(m.players), f["sizes"])
        self.animate_draw(groups, order)

    def animate_draw(self, groups, order):
        """Reveals the ballot one ball at a time, then saves the groups."""
        m, t = self.m, self.groups_txt
        where = {p: gi for gi, g in enumerate(groups) for p in g}
        self.drawing = True
        busy = (self.lock_btn, self.fmt_box, self.pick, self.new_entry, self.add_btn, *self.p_btns)
        for w in busy: w.config(state="disabled")
        delay = max(120, 5000 // len(order))
        shown = [[] for _ in groups]

        def show(i):
            t.config(state="normal"); t.delete("1.0", "end")
            t.insert("end", f"DRAWING… ball {i} of {len(order)}\n\n" if i < len(order) else "DRAW COMPLETE\n\n")
            if i:
                p = order[i - 1]; t.insert("end", f"Ball {i}:  {m.players[p]}  →  Group {GL(where[p])}\n\n")
            for gi, g in enumerate(shown):
                t.insert("end", f"Group {GL(gi)}\n" + "".join(f"   {m.players[p]}\n" for p in g) + "   ·\n" * (len(groups[gi]) - len(g)) + "\n")
            t.config(state="disabled")

        def step(i=0):
            if i < len(order):
                p = order[i]; shown[where[p]].append(p)
                show(i + 1); self.after(delay, step, i + 1)
            else:
                self.drawing = False
                self.pick.config(state="readonly")
                self.d["groups"] = [[m.players[p] for p in g] for g in groups]
                self.d["drawnAt"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                self.save()
        show(0); self.after(delay, step)

    def chosen_format(self):
        fm = formats(len(self.m.players))
        i = self.fmt_box.current()
        return fm[i] if 0 <= i < len(fm) else recommended(len(self.m.players))

    def ensure_locked(self):
        if self.m.drawn: return True
        messagebox.showinfo("Draw first", "Results can be entered once the groups are drawn.\n\nMake the draw in the “Players & groups” tab.")
        return False

    # ── results ──
    def set_result(self, key, a, b, sets):
        A, B = self.m.players[a].lower(), self.m.players[b].lower()
        lst = [e for e in self.d[key] if {str(e.get("a", "")).strip().lower(), str(e.get("b", "")).strip().lower()} != {A, B}]
        if sets:
            lst.append({"a": self.m.players[a], "b": self.m.players[b], "sets": [f"{x}-{y}" for x, y in sets]})
        self.d[key] = lst
        self.save()

    def edit_group_result(self):
        sel = self.gtree.selection()
        if not sel or not self.m or not self.m.drawn: return
        gi, a, b = map(int, sel[0].split(":"))
        if not self.ensure_locked(): return
        m = self.m
        dlg = ScoreDialog(self, f"Group {GL(gi)}: {m.players[a]} vs {m.players[b]}", m.players[a], m.players[b], m.best_of, m.lookup(m.gr, a, b))
        if dlg.result is not None:
            self.set_result("groupResults", a, b, dlg.result)
            if self.gtree.exists(sel[0]): self.gtree.selection_set(sel[0]); self.gtree.see(sel[0])

    def edit_ko_result(self):
        sel = self.ktree.selection()
        if not sel or not self.m: return
        a, b = map(int, sel[0].split(":")[1:])
        if a < 0 or b < 0:
            messagebox.showinfo("Knockout", "This match's players aren't known yet: earlier results are still missing."); return
        m = self.m
        stage = self.ktree.item(sel[0], "values")[1]
        dlg = ScoreDialog(self, f"{stage}: {m.players[a]} vs {m.players[b]}", m.players[a], m.players[b], m.best_of, m.lookup(m.kr, a, b))
        if dlg.result is not None:
            self.set_result("knockoutResults", a, b, dlg.result)

    # ── play order of the group matches ──
    def keys_in_order(self): return [f"{gi}:{a}:{b}" for gi, _, a, b in self.m.schedule]

    def save_order(self, keys, select=None):
        m = self.m
        self.d["matchOrder"] = [[m.players[int(a)], m.players[int(b)]] for a, b in (k.split(":")[1:] for k in keys)]
        self.save()
        if select and self.gtree.exists(select): self.gtree.selection_set(select); self.gtree.focus(select); self.gtree.see(select)

    def move_match(self, key, pos):
        keys = self.keys_in_order()
        if key not in keys: return
        pos = max(0, min(pos, len(keys) - 1))
        if keys.index(key) == pos: return
        keys.remove(key); keys.insert(pos, key)
        self.save_order(keys, key)

    def shift_match(self, step):
        sel = self.gtree.selection()
        if not sel or not self.m or not self.m.drawn: return
        # with a filter active, jump past the hidden matches to the neighbouring visible one
        vis, keys = list(self.gtree.get_children()), self.keys_in_order()
        i = vis.index(sel[0]) + step
        if 0 <= i < len(vis): self.move_match(sel[0], keys.index(vis[i]))

    def move_match_to(self):
        sel = self.gtree.selection()
        if not sel or not self.m or not self.m.drawn: return
        n = len(self.m.schedule)
        pos = simpledialog.askinteger("Move match", f"New position (1–{n}):", parent=self, minvalue=1, maxvalue=n,
                                      initialvalue=self.keys_in_order().index(sel[0]) + 1)
        if pos: self.move_match(sel[0], pos - 1)

    def reset_order(self):
        if not self.m or not self.m.drawn or "matchOrder" not in self.d: return
        if messagebox.askyesno("Reset order", "Put every group match back in the default order (round 1 of every group, then round 2…)?\n\nResults are kept."):
            self.d.pop("matchOrder", None); self.save()

    def drag_start(self, e):
        row = self.gtree.identify_row(e.y)
        self.drag = row if row and self.gtree.identify_region(e.x, e.y) == "cell" else None

    def drag_motion(self, e):
        if not self.drag: return
        self.gtree.config(cursor="sb_v_double_arrow")
        tgt = self.gtree.identify_row(e.y)
        if tgt and tgt != self.drag:
            self.gtree.move(self.drag, "", self.gtree.index(tgt)); self.dragged = True  # preview only, saved on release

    def drag_end(self, e):
        src, moved, self.drag, self.dragged = self.drag, getattr(self, "dragged", False), None, False
        self.gtree.config(cursor="")
        if not src or not moved or not self.m or not self.m.drawn: return
        vis, keys = list(self.gtree.get_children()), self.keys_in_order()
        if len(vis) < 2: return
        i, rest = vis.index(src), [k for k in keys if k != src]
        # place it right after the visible match now above it (or before the one below when it is first)
        rest.insert(rest.index(vis[i - 1]) + 1 if i > 0 else rest.index(vis[1]), src)
        if rest != keys: self.save_order(rest, src)
        else: self.refresh_group_matches(); self.gtree.selection_set(src)

    # ── publish ──
    def publish(self):
        if not messagebox.askyesno("Publish", "Encrypt the tournaments and upload them to the website?\n\n"
                                   "Only the encrypted files in data/ are committed and pushed to GitHub."):
            return
        self.config(cursor="watch"); self.update()
        log = []
        try:
            if ttt.publish_all(log=log.append):
                raise RuntimeError("Some tournament files have errors:\n" + "\n".join(log))
            git("add", "-A", "--", "data").check_returncode()
            if git("diff", "--cached", "--quiet", "--", "data").returncode:
                problems = ttt.safety_problems(staged=True)
                if problems:
                    raise RuntimeError("Safety check failed, nothing was committed:\n" + "\n".join(problems))
                # generic message: commit messages are public and must not reveal tournament names
                r = git("commit", "-m", "Update tournament data", "--", "data")
                if r.returncode: raise RuntimeError(r.stderr or r.stdout)
            ahead = git("rev-list", "--count", "@{u}..HEAD")
            if ahead.returncode or ahead.stdout.strip() != "0":
                r = git("push")
                if r.returncode: raise RuntimeError("git push failed:\n" + (r.stderr or r.stdout))
                msg = "Published. The website updates in about a minute."
            else:
                msg = "Nothing new to publish: the website is already up to date."
            messagebox.showinfo("Publish", msg + (f"\n\n{pages_url()}" if pages_url() else ""))
        except Exception as e:
            messagebox.showerror("Publish failed", str(e))
        finally:
            self.config(cursor=""); self.refresh_status()

    def refresh_status(self):
        if not self.code: self.status.config(text=""); return
        pending = not ttt.is_published(self.code)
        if not pending:
            fid = f"data/{ttt.file_id(self.code)}.json"
            pending = bool(git("status", "--porcelain", "--", fid, timeout=10).stdout.strip()) or \
                git("rev-list", "--count", "@{u}..HEAD", "--", fid, timeout=10).stdout.strip() not in ("", "0")
        self.status.config(text="● Changes not published yet" if pending else "✓ Website up to date",
                           foreground="#e37400" if pending else "#188038")

    def on_close(self):
        if self.code and not ttt.is_published(self.code):
            ans = messagebox.askyesnocancel("Unpublished changes", "Some changes are not on the website yet. Publish now?")
            if ans is None: return
            if ans: self.publish()
        self.destroy()

    # ── refresh views ──
    def refresh(self):
        has = self.m is not None
        for i in range(1, 5): self.nb.tab(i, state="normal" if has else "disabled")
        if not has:
            for v in (self.v_name, self.v_date, self.v_best, self.v_code, self.v_link): v.set("")
            self.status.config(text="No tournament yet: press New…"); return
        self.v_name.set(self.d.get("name", "")); self.v_date.set(self.d.get("date", "")); self.v_best.set(str(self.m.best_of))
        self.v_code.set(self.code); base = pages_url(); self.v_link.set(f"{base}tournament.html#{self.code}" if base else f"tournament.html#{self.code}")
        self.refresh_players(); self.refresh_group_matches(); self.refresh_ko(); self.refresh_standings(); self.refresh_status()

    def refresh_players(self):
        m, sel = self.m, self.selected_player()
        self.plist.delete(0, "end")
        for i, p in enumerate(m.players): self.plist.insert("end", f"{i + 1:>2}.  {p}")
        if sel is not None and sel < len(m.players): self.plist.selection_set(sel)
        N = len(m.players)
        self.quorum_lbl.config(text=f"{N} player{'s' if N != 1 else ''} · quorum reached" if N >= QUORUM else f"{N} of {QUORUM} players needed for the quorum",
                               foreground="#188038" if N >= QUORUM else ERR)
        state = "disabled" if m.locked else "normal"
        for w in [self.new_entry, self.add_btn, *self.p_btns]: w.config(state=state)
        if m.quorum:
            fm = formats(N); rec = recommended(N)
            self.fmt_box["values"] = [format_label(f, f["G"] == rec["G"]) for f in fm]
            if m.drawn:
                cur = next((i for i, f in enumerate(fm) if f["G"] == m.G and f["sizes"] == sorted((len(g) for g in m.groups), reverse=True)), -1)
                self.fmt_box.set(format_label({"G": m.G, "K": m.K, "T": m.T, "sizes": [len(g) for g in m.groups]}) if cur < 0 else self.fmt_box["values"][cur])
            elif self.fmt_box.current() < 0 or self.fmt_box.current() >= len(fm):
                self.fmt_box.current(fm.index(rec))
            self.fmt_box.config(state="disabled" if m.locked else "readonly")
            self.lock_btn.config(state="normal", text="Undo draw…" if m.drawn else "🎲 Draw groups")
        else:
            self.fmt_box.set(""); self.fmt_box["values"] = []; self.fmt_box.config(state="disabled")
            self.lock_btn.config(state="disabled", text="🎲 Draw groups")
        self.refresh_groups_preview()

    def refresh_groups_preview(self):
        if getattr(self, "drawing", False): return
        m, t = self.m, self.groups_txt
        t.config(state="normal"); t.delete("1.0", "end")
        if not m.quorum:
            t.insert("end", f"Add at least {QUORUM} players before the draw." if len(m.players) < QUORUM else f"Too many players (maximum {MAX_PLAYERS}).")
        elif not m.drawn:
            f = self.chosen_format()
            t.insert("end", "NOT DRAWN YET\n\n"
                     f"Format: {format_label(f)}\n\n"
                     "Press “🎲 Draw groups” to draw every player completely at random,\n"
                     "like balls from a pot. The order of the player list has no influence.\n"
                     "Each ball goes to the next group in turn: A, B, C, A, B, C…\n\n"
                     "Until the draw is published, the website shows “Waiting for the draw”.")
        else:
            t.insert("end", f"DRAWN AT RANDOM{' on ' + self.d['drawnAt'] if self.d.get('drawnAt') else ''}: these groups are final.\n\n")
            for gi, g in enumerate(m.groups):
                t.insert("end", f"Group {GL(gi)}\n" + "".join(f"   {m.players[p]}\n" for p in g) + "\n")
        t.config(state="disabled")

    def refresh_group_matches(self):
        tv, m = self.gtree, self.m
        tv.delete(*tv.get_children())
        if not m or not m.drawn:
            self.g_info.config(text=f"Needs at least {QUORUM} players." if not (m and m.quorum) else "Make the draw in “Players & groups” first."); return
        flt, done_n, b2b, prev = self.v_gfilter.get(), 0, 0, set()
        for n, (gi, ri, a, b) in enumerate(m.schedule, 1):
            s = m.lookup(m.gr, a, b); done_n += bool(s)
            back = bool(prev & {a, b}); prev = {a, b}; b2b += back   # a player also plays the match just before
            if (flt == "To play" and s) or (flt == "Played" and not s): continue
            sa, sb, _, _ = summ(s) if s else (0, 0, 0, 0)
            tv.insert("", "end", iid=f"{gi}:{a}:{b}", tags=("done" if s else "b2b" if back else "todo",),
                      values=(n, GL(gi), ri + 1, m.players[a], f"{sa} – {sb}" if s else "—", m.players[b], ", ".join(f"{x}-{y}" for x, y in s) if s else ""))
        self.g_info.config(text=f"{done_n} of {len(m.schedule)} matches played  ·  double-click a match to enter or edit its score"
                           + (f"  ·  {b2b} back-to-back (orange)" if b2b else ""))

    def refresh_ko(self):
        tv, m = self.ktree, self.m
        tv.delete(*tv.get_children())
        if not m or not m.drawn:
            self.k_info.config(text=f"Needs at least {QUORUM} players." if not (m and m.quorum) else "Make the draw in “Players & groups” first."); return
        km = m.ko_model()
        ms = [x for _, r in km["rounds"] for x in r] + ([km["third"]] if km["third"] else [])
        for x in sorted(ms, key=lambda x: x["num"]):
            a, b, s = x["a"], x["b"], x["sets"]
            ready = a is not None and b is not None
            sa, sb, _, _ = summ(s) if s else (0, 0, 0, 0)
            tv.insert("", "end", iid=f"{x['num']}:{a if a is not None else -1}:{b if b is not None else -1}", tags=("done" if s else "todo" if ready else "wait",),
                      values=(f"M{x['num']}", x["stage"], m.players[a] if a is not None else x["la"], f"{sa} – {sb}" if s else "—",
                              m.players[b] if b is not None else x["lb"], ", ".join(f"{p}-{q}" for p, q in s) if s else ""))
        champ = km["champion"]
        self.k_info.config(text=f"Champion: {m.players[champ]}" if champ is not None else
                           "Double-click a match to enter its score." if km["groups_done"] else "The bracket fills in when every group is complete.")

    def refresh_standings(self):
        t, m = self.stand_txt, self.m
        t.config(state="normal"); t.delete("1.0", "end")
        if not m.drawn:
            t.insert("end", f"Needs at least {QUORUM} players." if not m.quorum else "The groups haven't been drawn yet.")
        else:
            w = max(10, *(len(p) for p in m.players)) + 2
            head = f"  #  {'Player':<{w}}{'P':>4}{'W':>4}{'SW':>5}{'Pts':>6}\n"
            for gi in range(m.G):
                order, st = m.rank_group(gi)
                t.insert("end", f"Group {GL(gi)}{'  (complete)' if m.group_done(gi) else ''}\n{head}")
                for i, p in enumerate(order):
                    s = st[p]; t.insert("end", f"{i + 1:>3}  {m.players[p]:<{w}}{s['p']:>4}{s['w']:>4}{s['sw']:>5}{s['pw']:>6}\n")
                t.insert("end", "\n")
            if m.T:
                t.insert("end", f"Best 3rd places ({m.T} qualify)\n")
                for i, r in enumerate(m.thirds_table()):
                    t.insert("end", f"{i + 1:>3}  {m.players[r['pid']]:<{w}} Group {GL(r['g'])}   W/M {r['wpm']:.2f}  SW/M {r['swpm']:.2f}  Pts/M {r['pwpm']:.1f}\n")
                t.insert("end", "\n")
            t.insert("end", "P played · W wins (1 point each) · SW sets won · Pts points scored in all sets\nOrder: W → SW → Pts → head-to-head")
        t.config(state="disabled")


if __name__ == "__main__":
    try:
        App().mainloop()
    except tk.TclError as e:
        sys.exit(f"Cannot open a window ({e}). Run this on a desktop session.")
