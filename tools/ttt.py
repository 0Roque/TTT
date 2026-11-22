#!/usr/bin/env python3
"""Tournament file tool.

Editable (private) files live in tournaments/<code>.json and are git-ignored.
Published files live in data/<id>.json: the id is derived from the code with HMAC-SHA256 and the content is
encrypted with AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC), both keyed by the code. Without the code, a published
file reveals nothing — not the code, the name, the players or the results.

  tools/ttt.py new "Autumn Cup 2026" [3|5|7]   create a tournament with a fresh 32-character code
  tools/ttt.py publish                         encrypt every tournaments/*.json into data/
  tools/ttt.py decrypt <code>                  restore tournaments/<code>.json from its published file
  tools/ttt.py check                           verify no readable tournament data is tracked or staged in git
  tools/ttt.py install-hook                    install a git pre-commit hook that runs that check on every commit
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


def create_tournament(name="Table Tennis Tournament", best_of=5) -> str:
    """Creates tournaments/<new code>.json and returns the code (does not publish)."""
    if int(best_of) not in (3, 5, 7):
        raise ValueError("bestOf must be 3, 5 or 7")
    SRC.mkdir(exist_ok=True)
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(32))
        if not (SRC / f"{code}.json").exists():
            break
    data = {"name": name, "date": date.today().strftime("%d/%m/%Y"), "bestOf": int(best_of),
            "players": [], "groupResults": [], "knockoutResults": []}
    (SRC / f"{code}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return code


def canonical(src: Path) -> bytes:
    return json.dumps(json.loads(src.read_text()), ensure_ascii=False, separators=(",", ":")).encode()


def is_published(code: str) -> bool:
    """True when data/ already holds an encrypted copy identical to tournaments/<code>.json."""
    try:
        out = OUT / f"{file_id(code)}.json"
        return decrypt(code, json.loads(out.read_text())) == canonical(SRC / f"{code}.json")
    except Exception:
        return False


def publish_all(log=print) -> int:
    """Encrypts every tournaments/*.json into data/. Returns the number of errors."""
    OUT.mkdir(exist_ok=True)
    sources = sorted(SRC.glob("*.json")) if SRC.exists() else []
    expected, errors = set(), 0
    for src in sources:
        code = src.stem
        if not CODE_RE.match(code):
            log(f"skip   {src.name}: file name must be the 32-character code"); errors += 1; continue
        try:
            plain = canonical(src)
        except json.JSONDecodeError as e:
            log(f"ERROR  {src.name}: invalid JSON — {e}"); errors += 1; continue
        out = OUT / f"{file_id(code)}.json"
        expected.add(out.name)
        name = json.loads(plain).get("name", "")
        if is_published(code):  # keep the file untouched when nothing changed (a new IV would make a noisy git diff)
            log(f"same   {code[:6]}…  {name}"); continue
        out.write_text(json.dumps(encrypt(code, plain)) + "\n")
        log(f"wrote  {code[:6]}…  {name}  →  data/{out.name}")
    orphans = [p.name for p in OUT.glob("*.json") if p.name not in expected]
    if orphans:
        log(f"note   {len(orphans)} file(s) in data/ have no source in tournaments/ on this machine (left untouched).")
    return errors


def cmd_new(name="Table Tennis Tournament", best_of="5"):
    if best_of not in ("3", "5", "7"):
        sys.exit("bestOf must be 3, 5 or 7")
    code = create_tournament(name, int(best_of))
    print(f"Tournament code: {code}")
    print(f"Edit:            tournaments/{code}.json   (private, never committed)")
    print(f"Share link:      tournament.html#{code}")
    cmd_publish()


def cmd_publish():
    ensure_hook()
    if publish_all():
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


DATA_NAME_RE = re.compile(r"^data/[0-9a-f]{64}\.json$")
BOX_KEYS = {"v", "iv", "ct", "tag"}


def safety_problems(staged=True) -> list:
    """Checks what is (about to be) committed: nothing from tournaments/, and only encrypted files in data/."""
    def git(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout
    if staged:
        paths = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]
        read = lambda p: git("show", f":{p}")
    else:
        paths = [p for p in git("ls-files").splitlines() if p and (ROOT / p).exists()]  # deleted files are not a leak
        read = lambda p: (ROOT / p).read_text()
    problems = []
    for p in paths:
        if p.startswith("tournaments/") or (p.endswith(".json") and not p.startswith("data/")):
            problems.append(f"{p}: readable tournament data must never be committed")
        elif p.startswith("data/"):
            if not DATA_NAME_RE.match(p):
                problems.append(f"{p}: only encrypted files named data/<64 hex>.json are allowed in data/")
                continue
            try:
                box = json.loads(read(p))
                ok = isinstance(box, dict) and set(box) == BOX_KEYS and all(base64.b64decode(box[k], validate=True) for k in ("iv", "ct", "tag"))
            except Exception:
                ok = False
            if not ok:
                problems.append(f"{p}: not an encrypted tournament file")
    return problems


def cmd_check():
    problems = safety_problems(staged=False) + safety_problems(staged=True)
    if problems:
        sys.exit("UNSAFE:\n  " + "\n  ".join(sorted(set(problems))))
    print("OK: no readable tournament data is tracked or staged.")


HOOK = """#!/bin/sh
# Installed by tools/ttt.py install-hook: blocks commits containing readable tournament data.
python3 -B "$(git rev-parse --show-toplevel)/tools/ttt.py" precommit
"""


def cmd_precommit():
    problems = safety_problems(staged=True)
    if problems:
        sys.exit("Commit blocked (tournament data safety check):\n  " + "\n  ".join(problems))


def ensure_hook() -> bool:
    """Installs the pre-commit safety hook if it is missing. Returns True when it was (re)installed."""
    hook = ROOT / ".git" / "hooks" / "pre-commit"
    if not (ROOT / ".git").is_dir() or (hook.exists() and hook.read_text() == HOOK):
        return False
    if hook.exists() and "ttt.py" not in hook.read_text():
        print(f"warning: {hook.relative_to(ROOT)} already exists and was left unchanged; add the line from HOOK to it", file=sys.stderr)
        return False
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK); hook.chmod(0o755)
    return True


def cmd_install_hook():
    print("Installed .git/hooks/pre-commit" if ensure_hook() else "Hook already installed.")


if __name__ == "__main__":
    cmds = {"new": cmd_new, "publish": cmd_publish, "decrypt": cmd_decrypt,
            "check": cmd_check, "install-hook": cmd_install_hook, "precommit": cmd_precommit}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    try:
        cmds[sys.argv[1]](*sys.argv[2:])
    except TypeError:
        sys.exit(__doc__)
