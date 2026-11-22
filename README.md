# Table Tennis Tournament

A static, read-only tournament viewer for GitHub Pages. Each tournament is opened with a **32-character code**. The files it publishes are **encrypted**, so anyone can browse the repository but cannot read a tournament or find its code.

- `index.html`: enter a tournament code.
- `tournament.html#<code>`: the tournament page, with phases, groups, ranking, best 3rds and the knockout bracket. The code is in the URL fragment (`#`), so browsers never send it to the server.

## How privacy works

| Where | What | In git? |
|---|---|---|
| `tournaments/<code>.json` | The readable file you edit | **No** (git-ignored, stays on your computer) |
| `data/<id>.json` | The encrypted copy the website loads | Yes |

- **File name:** `<id>` is HMAC-SHA256(code), a 64-character hex string. The code cannot be worked out from it.
- **Content:** encrypted with AES-256, using a key derived from the code, and protected with an HMAC integrity check.
- **Without the code:** a published file reveals nothing, not even the tournament name. A file that has been tampered with is rejected.
- **Strength:** a code has about 165 bits of randomness, so guessing it is not feasible.

Keep the code private: anyone who has it can view the tournament.

## Commands

```bash
tools/ttt.py new "Autumn Cup 2026" 5    # create a tournament (best of 3/5/7) and print its code
tools/ttt.py publish                    # encrypt every tournaments/*.json into data/
tools/ttt.py decrypt <code>             # restore tournaments/<code>.json from data/ (e.g. on another computer)
```

You need `python3` and `openssl`. Nothing else is required.

**Updating results:** edit `tournaments/<code>.json`, run `tools/ttt.py publish`, then commit and push `data/`. GitHub Pages republishes in about a minute, and viewers can press **↻ Refresh**. `publish` leaves unchanged tournaments untouched, so git only shows the files that really changed.

## Rules

- **Quorum:** a tournament starts only when it has **at least 6 players** (maximum 40). Until then the page shows "Waiting for players".
- **Groups:** players are split into groups of 3–5 that play a round robin. Unless `groups` is set, players are placed in snake order, so the order of the `players` list is the seeding.
- **Group points:** each win is **1 point**. The ranking table shows **wins**, **sets won** and **points** (the sum of points scored across all sets). Order: wins, then sets won, then points, then head-to-head when exactly two players are tied.
- **Knockout:** the top 2 of each group go through, plus the best 3rd places when the bracket needs them. Best 3rds are compared per match, because groups can have different sizes. A 3rd-place match is played.

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
| `players` | Participant names, in seeding order. Names must be unique. |
| `groups` | *Optional.* Your own group draw. Leave it out to use the automatic seeded draw. Every player must be in exactly one group of at least 3. |
| `groupResults` | One entry per finished group match. The `a`/`b` order is free, and `sets` are from `a`'s point of view. |
| `knockoutResults` | Same format. The page places each result in the bracket by matching the two players. |
| `bestOf` | 3, 5 or 7 (default 5). |

- Sets can be written as `"11-7"` or `[11, 7]`. Each set must be a valid score: first to 11, win by 2.
- Only finished matches count. Points, wins and rankings are all calculated from the set scores, so you never type totals.
- The page tells you if anything in the file is wrong, for example an unknown name, an invalid score or a duplicate match.

## Hosting on GitHub Pages

Push the repository, then open **Settings → Pages** and deploy from the branch root. `.nojekyll` makes GitHub serve the files as they are.

To test locally, run `python3 -m http.server` and open <http://localhost:8000>. Opening the file directly with `file://` does not work, because browsers block it from loading files and from decrypting.
