#!/usr/bin/env python3
"""Tournament file tool.

Editable (private) files live in tournaments/<code>.json and are git-ignored.
Published files live in data/<id>.json: the id is derived from the code with HMAC-SHA256 and the content is
encrypted with AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC), both keyed by the code. Without the code, a published
file reveals nothing — not the code, the name, the players or the results.

  tools/ttt.py new "Autumn Cup 2026" [3|5|7]   create a tournament with a fresh 32-character code
  tools/ttt.py publish                         encrypt every tournaments/*.json into data/
  tools/ttt.py decrypt <code>                  restore tournaments/<code>.json from its published file
"""
import base64, hashlib, hmac, json, os, re, secrets, string, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "tournaments", ROOT / "data"
CODE_RE = re.compile(r"^[a-z0-9]{32}$")
ALPHABET = string.ascii_lowercase + string.digits


def derive(code: str, label: str) -> bytes:
    return hmac.new(code.encode(), label.encode(), hashlib.sha256).digest()


def file_id(code: str) -> str:
    return derive(code, "ttt-file").hex()


def openssl(args, data: bytes) -> bytes:
    return subprocess.run(["openssl", "enc", "-aes-256-cbc", *args], input=data, capture_output=True, check=True).stdout


def encrypt(code: str, plain: bytes) -> dict:
    iv = os.urandom(16)
    ct = openssl(["-K", derive(code, "ttt-enc").hex(), "-iv", iv.hex()], plain)
    tag = hmac.new(derive(code, "ttt-mac"), iv + ct, hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "iv": b64(iv), "ct": b64(ct), "tag": b64(tag)}


def decrypt(code: str, box: dict) -> bytes:
    iv, ct, tag = (base64.b64decode(box[k]) for k in ("iv", "ct", "tag"))
    if not hmac.compare_digest(tag, hmac.new(derive(code, "ttt-mac"), iv + ct, hashlib.sha256).digest()):
        raise ValueError("integrity check failed (wrong code or corrupted file)")
    return openssl(["-d", "-K", derive(code, "ttt-enc").hex(), "-iv", iv.hex()], ct)


def check_code(code: str) -> str:
    code = code.strip().lower()
    if not CODE_RE.match(code):
        sys.exit(f"Invalid code {code!r}: expected 32 characters a-z / 0-9.")
    return code


def cmd_new(name="Table Tennis Tournament", best_of="5"):
    if best_of not in ("3", "5", "7"):
        sys.exit("bestOf must be 3, 5 or 7")
    SRC.mkdir(exist_ok=True)
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(32))
        if not (SRC / f"{code}.json").exists():
            break
    data = {"name": name, "date": date.today().strftime("%d/%m/%Y"), "bestOf": int(best_of),
            "players": [], "groupResults": [], "knockoutResults": []}
    (SRC / f"{code}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Tournament code: {code}")
    print(f"Edit:            tournaments/{code}.json   (private, never committed)")
    print(f"Share link:      tournament.html#{code}")
    cmd_publish()


def cmd_publish():
    OUT.mkdir(exist_ok=True)
    sources = sorted(SRC.glob("*.json")) if SRC.exists() else []
    expected, errors = set(), 0
    for src in sources:
        code = src.stem
        if not CODE_RE.match(code):
            print(f"skip   {src.name}: file name must be the 32-character code"); errors += 1; continue
        try:
            plain = json.dumps(json.loads(src.read_text()), ensure_ascii=False, separators=(",", ":")).encode()
        except json.JSONDecodeError as e:
            print(f"ERROR  {src.name}: invalid JSON — {e}"); errors += 1; continue
        out = OUT / f"{file_id(code)}.json"
        expected.add(out.name)
        try:  # keep the file untouched when nothing changed (a new IV would make a noisy git diff)
            if decrypt(code, json.loads(out.read_text())) == plain:
                print(f"same   {code[:6]}…  {json.loads(plain).get('name', '')}"); continue
        except Exception:
            pass
        out.write_text(json.dumps(encrypt(code, plain)) + "\n")
        print(f"wrote  {code[:6]}…  {json.loads(plain).get('name', '')}  →  data/{out.name}")
    orphans = [p.name for p in OUT.glob("*.json") if p.name not in expected]
    if orphans:
        print(f"note   {len(orphans)} file(s) in data/ have no source in tournaments/ on this machine (left untouched).")
    if errors:
        sys.exit(1)


def cmd_decrypt(code):
    code = check_code(code)
    out = OUT / f"{file_id(code)}.json"
    if not out.exists():
        sys.exit("No published tournament for this code.")
    plain = json.loads(decrypt(code, json.loads(out.read_text())))
    SRC.mkdir(exist_ok=True)
    dst = SRC / f"{code}.json"
    if dst.exists():
        sys.exit(f"{dst.relative_to(ROOT)} already exists — not overwriting.")
    dst.write_text(json.dumps(plain, indent=2, ensure_ascii=False) + "\n")
    print(f"Restored {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    cmds = {"new": cmd_new, "publish": cmd_publish, "decrypt": cmd_decrypt}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    try:
        cmds[sys.argv[1]](*sys.argv[2:])
    except TypeError:
        sys.exit(__doc__)
