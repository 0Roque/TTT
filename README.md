# Table Tennis Tournament

A static, **display-only** tournament viewer for GitHub Pages. Each tournament is opened with a **32-character code**.

**Updates happen only offline**, on the organiser's computer, with the manager app or the command-line tool. The website has no login, no forms and no way to change anything. It downloads an encrypted file and shows it. The files it publishes are **encrypted**, so anyone can browse the repository but cannot read a tournament or find its code.

- `index.html`: enter a tournament code.
- `tournament.html#<code>`: the tournament page, with phases, groups, ranking, best 3rds and the knockout bracket. The code is in the URL fragment (`#`), so browsers never send it to the server.

## Data security

| Where | What | In git / on the website? |
|---|---|---|
| `tournaments/<code>.json` | The readable file you edit | **Never**: git-ignored, stays on your computer |
| `data/<id>.json` | The encrypted copy the website loads | Yes |

- **File name:** `<id>` is HMAC-SHA256(code), a 64-character hex string. The code cannot be worked out from it.
- **Content:** encrypted with AES-256, using a key derived from the code, and protected with an HMAC integrity check.
- **Without the code:** a published file reveals nothing, not even the tournament name. A file that has been tampered with is rejected.
- **Strength:** a code has about 165 bits of randomness, so guessing it is not feasible.
- **URL:** the code is in the fragment (`#…`), so browsers never send it to GitHub's servers, and the pages send no referrer.

**Safeguards against mistakes:**

- **`.gitignore`:** ignores `tournaments/`, plus backup and editor copies (`*.bak`, `*~`, `*.swp`, …) and `.env` files.
- **Pre-commit hook:** `.git/hooks/pre-commit` makes git **refuse** any commit that contains something from `tournaments/`, a readable JSON anywhere, or a file in `data/` that isn't an encrypted tournament. This holds even with `git add -f`. The manager app and `tools/ttt.py publish` install the hook automatically. On a fresh clone, run `tools/ttt.py install-hook`.
- **Checking by hand:** `tools/ttt.py check` checks everything tracked and staged.
- **Publishing:** the manager app commits **only** `data/`, with the generic message "Update tournament data". Commit messages are public, so they never contain names or codes.
- **Display-only pages:** a Content Security Policy only lets them load their own scripts and data files and Google Fonts, and blocks form submissions. They never store or send anything.

**Keep the code private:** anyone who has it can view the tournament. If a code leaks, create a new tournament; codes can't be revoked.

**Back up your `tournaments/` folder.** If you lose it, `tools/ttt.py decrypt <code>` rebuilds a tournament from its published file, as long as you still have the code.

## Manager app (recommended)

```bash
python3 tools/manager.py
```

A desktop window for running a tournament offline. Every change is saved straight away to the private file in `tournaments/`.

1. **New…**: create a tournament. Its code is shown in the **Details** tab, with buttons to copy the code and the share link.
2. **Players & groups**: add players one at a time or with **Add many…** (one name per line). Once there are at least 6, choose a group format and press **🎲 Draw groups** for a random draw (see *The group draw* below).
3. **Group matches**: double-click a match to enter its set scores. Scores are checked: first to 11, win by 2, and the match must be finished.
4. **Knockout**: matches appear as soon as their players are known. Double-click to enter the score.
5. **Standings**: group tables with W / SW / Pts and the best 3rd places.
6. **Publish**: encrypts the tournaments, then commits and pushes **only** `data/` to GitHub. The status next to the button shows whether the website is up to date.

The draw stays fixed while results come in. To change the player list afterwards, press **Undo draw…**, which also deletes all results, and then draw again. Renaming a player is always allowed and updates their results too.

The app needs tkinter, which comes with Python on most systems. On Fedora, if it's missing: `sudo dnf install python3-tkinter`.

## Commands

```bash
tools/ttt.py new "Autumn Cup 2026" 5    # create a tournament (best of 3/5/7) and print its code
tools/ttt.py publish                    # encrypt every tournaments/*.json into data/
tools/ttt.py decrypt <code>             # restore tournaments/<code>.json from data/ (e.g. on another computer)
tools/ttt.py check                      # verify no readable tournament data is tracked or staged in git
tools/ttt.py install-hook               # install the pre-commit safety hook (done automatically by publish / the app)
```

You need `python3` and `openssl`. Nothing else is required.

**Updating results:** edit `tournaments/<code>.json`, run `tools/ttt.py publish`, then commit and push `data/`. GitHub Pages republishes in about a minute, and viewers can press **↻ Refresh**. `publish` leaves unchanged tournaments untouched, so git only shows the files that really changed.

## Rules

- **Quorum:** a tournament starts only when it has **at least 6 players** (maximum 40). Until then the page shows "Waiting for players".
- **Groups:** players are split into groups of 3–5 that play a round robin, using a **completely random draw** (see below).
- **Group points:** each win is **1 point**. The ranking table shows **wins**, **sets won** and **points** (the sum of points scored across all sets). Order: wins, then sets won, then points, then head-to-head when exactly two players are tied.
- **Knockout:** the top 2 of each group go through, plus the best 3rd places when the bracket needs them. Best 3rds are compared per match, because groups can have different sizes. A 3rd-place match is played.

## The group draw

The groups are drawn **completely at random**, like balls drawn from a pot. There is no seeding.

1. The manager app shuffles all players with the operating system's **cryptographic random generator** (Python `secrets`). The order the names were typed in has no influence.
2. The balls are drawn one at a time, and each goes to the next group in turn (A, B, C, A, B, C…), skipping groups that are already full. The app shows this as an animated draw.
3. The draw is saved with its date and time, and the website shows *"Groups drawn at random on DD/MM/YYYY HH:MM"*.

Until the draw is published, the website shows **"Waiting for the draw"** with the registered players. The website never draws groups itself.

## Tournament format by number of players

The format depends on the number of players. Groups have 3–5 players and play a round robin (everyone plays everyone in their group). The knockout bracket always has 4, 8 or 16 places. When the group winners and runners-up don't fill the bracket, the best 3rd-placed players take the remaining places.

The table shows the **default (recommended)** format. When making the draw in the manager app you can choose another valid format; for example, 12 players can also play 4 groups of 3.

| Players | Groups | Group sizes | Who reaches the knockout | Knockout starts at | Group matches | Knockout matches* | Total matches |
|---:|---:|---|---|---|---:|---:|---:|
| 6 | 2 | 2×3 | Top 2 of each group (4) | Semi-finals | 6 | 4 | 10 |
| 7 | 2 | 4 + 3 | Top 2 of each group (4) | Semi-finals | 9 | 4 | 13 |
| 8 | 2 | 2×4 | Top 2 of each group (4) | Semi-finals | 12 | 4 | 16 |
| 9 | 2 | 5 + 4 | Top 2 of each group (4) | Semi-finals | 16 | 4 | 20 |
| 10 | 3 | 4 + 2×3 | Top 2 of each group + 2 best 3rds (8) | Quarter-finals | 12 | 8 | 20 |
| 11 | 3 | 2×4 + 3 | Top 2 of each group + 2 best 3rds (8) | Quarter-finals | 15 | 8 | 23 |
| 12 | 3 | 3×4 | Top 2 of each group + 2 best 3rds (8) | Quarter-finals | 18 | 8 | 26 |
| 13 | 3 | 5 + 2×4 | Top 2 of each group + 2 best 3rds (8) | Quarter-finals | 22 | 8 | 30 |
| 14 | 4 | 2×4 + 2×3 | Top 2 of each group (8) | Quarter-finals | 18 | 8 | 26 |
| 15 | 4 | 3×4 + 3 | Top 2 of each group (8) | Quarter-finals | 21 | 8 | 29 |
| 16 | 4 | 4×4 | Top 2 of each group (8) | Quarter-finals | 24 | 8 | 32 |
| 17 | 4 | 5 + 3×4 | Top 2 of each group (8) | Quarter-finals | 28 | 8 | 36 |
| 18 | 4 | 2×5 + 2×4 | Top 2 of each group (8) | Quarter-finals | 32 | 8 | 40 |
| 19 | 4 | 3×5 + 4 | Top 2 of each group (8) | Quarter-finals | 36 | 8 | 44 |
| 20 | 6 | 2×4 + 4×3 | Top 2 of each group + 4 best 3rds (16) | Round of 16 | 24 | 16 | 40 |
| 21 | 6 | 3×4 + 3×3 | Top 2 of each group + 4 best 3rds (16) | Round of 16 | 27 | 16 | 43 |
| 22 | 6 | 4×4 + 2×3 | Top 2 of each group + 4 best 3rds (16) | Round of 16 | 30 | 16 | 46 |
| 23 | 6 | 5×4 + 3 | Top 2 of each group + 4 best 3rds (16) | Round of 16 | 33 | 16 | 49 |
| 24 | 6 | 6×4 | Top 2 of each group + 4 best 3rds (16) | Round of 16 | 36 | 16 | 52 |
| 25 | 6 | 5 + 5×4 | Top 2 of each group + 4 best 3rds (16) | Round of 16 | 40 | 16 | 56 |
| 26 | 7 | 5×4 + 2×3 | Top 2 of each group + 2 best 3rds (16) | Round of 16 | 36 | 16 | 52 |
| 27 | 7 | 6×4 + 3 | Top 2 of each group + 2 best 3rds (16) | Round of 16 | 39 | 16 | 55 |
| 28 | 7 | 7×4 | Top 2 of each group + 2 best 3rds (16) | Round of 16 | 42 | 16 | 58 |
| 29 | 7 | 5 + 6×4 | Top 2 of each group + 2 best 3rds (16) | Round of 16 | 46 | 16 | 62 |
| 30 | 8 | 6×4 + 2×3 | Top 2 of each group (16) | Round of 16 | 42 | 16 | 58 |
| 31 | 8 | 7×4 + 3 | Top 2 of each group (16) | Round of 16 | 45 | 16 | 61 |
| 32 | 8 | 8×4 | Top 2 of each group (16) | Round of 16 | 48 | 16 | 64 |
| 33 | 8 | 5 + 7×4 | Top 2 of each group (16) | Round of 16 | 52 | 16 | 68 |
| 34 | 8 | 2×5 + 6×4 | Top 2 of each group (16) | Round of 16 | 56 | 16 | 72 |
| 35 | 8 | 3×5 + 5×4 | Top 2 of each group (16) | Round of 16 | 60 | 16 | 76 |
| 36 | 8 | 4×5 + 4×4 | Top 2 of each group (16) | Round of 16 | 64 | 16 | 80 |
| 37 | 8 | 5×5 + 3×4 | Top 2 of each group (16) | Round of 16 | 68 | 16 | 84 |
| 38 | 8 | 6×5 + 2×4 | Top 2 of each group (16) | Round of 16 | 72 | 16 | 88 |
| 39 | 8 | 7×5 + 4 | Top 2 of each group (16) | Round of 16 | 76 | 16 | 92 |
| 40 | 8 | 8×5 | Top 2 of each group (16) | Round of 16 | 80 | 16 | 96 |

\* Knockout matches include the 3rd-place match. Each player plays 2–4 group matches (group size − 1).

How the default is chosen: about 4 players per group. When two options are equally close, the one with more groups wins.

## Tournament file format

```json
{
  "name": "Autumn Cup 2026",
  "date": "22/11/2026",
  "bestOf": 5,
  "players": ["Ana", "Bruno", "Clara", "David", "Eva", "Filipe"],
  "groups": [["Ana", "David", "Eva"], ["Bruno", "Clara", "Filipe"]],
  "groupResults": [
    { "a": "Ana", "b": "David", "sets": ["11-7", "9-11", "11-5", "11-8"] }
  ],
  "knockoutResults": [
    { "a": "Ana", "b": "Clara", "sets": [[11, 4], [11, 9], [13, 11]] }
  ]
}
```

| Field | Meaning |
|---|---|
| `players` | Participant names, in any order. Names must be unique. |
| `groups` | Written by the app's random draw. Without it, the website shows "Waiting for the draw". Every player must be in exactly one group of at least 3. |
| `drawnAt` | Date and time of the draw (`DD/MM/YYYY HH:MM`), written by the app. |
| `groupResults` | One entry per finished group match. The `a`/`b` order is free, and `sets` are from `a`'s point of view. |
| `knockoutResults` | Same format. The page places each result in the bracket by matching the two players. |
| `bestOf` | 3, 5 or 7 (default 5). |

- Sets can be written as `"11-7"` or `[11, 7]`. Each set must be a valid score: first to 11, win by 2.
- Only finished matches count. Points, wins and rankings are all calculated from the set scores, so you never type totals.
- The page tells you if anything in the file is wrong, for example an unknown name, an invalid score or a duplicate match.

## Hosting on GitHub Pages

Push the repository, then open **Settings → Pages** and deploy from the branch root. `.nojekyll` makes GitHub serve the files as they are.

To test locally, run `python3 -m http.server` and open <http://localhost:8000>. Opening the file directly with `file://` does not work, because browsers block it from loading files and from decrypting.
