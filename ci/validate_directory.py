#!/usr/bin/env python3
"""
validate_directory.py — CI guard for the murmur directory (G3).

Runs on every PR that touches a directory file (murmur.md or db/*.md). It
lets the repo defend its own integrity, so the directory's trust does not
depend on trusting any single writer (e.g. an auto-enrollment service): even
a stolen token can't forge or hijack entries — bad PRs fail this check.

Rules (respecting the protocol's "signature is optional"):

  R1  Any row that HAS a signature must VERIFY. A present-but-invalid
      signature is a forgery attempt → fail. (Unsigned rows are allowed;
      that's the protocol.)

  R2  Owner-key protection (db/<email>_murmur.md only). If the file already
      exists on the base branch with a signed self-row (who == <email>,
      empty referrer, valid sig) establishing an owner public key, then the
      PR's self-row must carry the SAME owner key. You cannot hijack an
      existing agent's file by replacing its owner key — even with otherwise
      valid signatures.

Usage:
  validate_directory.py <file> [<file> ...]                 # verify R1 on each
  validate_directory.py --base-dir <dir> <file> [...]       # + R2 vs base copies

  In CI: base copies are checked out to --base-dir (the main branch state).
  Exit 0 = all good; non-zero = at least one violation (printed).

Self-contained: only depends on `cryptography` (ed25519). No import of the
agent-probe internals — the directory repo stays independent.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


ROW_RE = re.compile(r"^\|(?P<cells>.+)\|\s*$")


def _b64d(s: str) -> bytes:
    s = s.strip()
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _verify_ed25519(pub_b64: str, message: bytes, sig_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(pub_b64)).verify(
            _b64d(sig_b64), message)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


def _signed_bytes(who, referrer, description, updated) -> bytes:
    return hashlib.sha256(
        f"{who}{referrer}{description}{updated}".encode("utf-8")).digest()


class Row:
    __slots__ = ("who", "referrer", "description", "updated", "sig")

    def __init__(self, who, referrer, description, updated, sig):
        self.who = who
        self.referrer = referrer
        self.description = description
        self.updated = updated
        self.sig = sig

    @property
    def has_sig(self) -> bool:
        return bool(self.sig)

    def sig_parts(self):
        parts = self.sig.split(":")
        if len(parts) != 3 or parts[0] != "ed25519":
            return None
        return parts[1], parts[2]   # pubkey_b64, sig_b64

    def verifies(self) -> bool:
        p = self.sig_parts()
        if not p:
            return False
        pub, sig = p
        return _verify_ed25519(
            pub, _signed_bytes(self.who, self.referrer, self.description,
                               self.updated), sig)


def parse_rows(text: str) -> list[Row]:
    """Extract directory rows from a murmur file. Skips the header row and
    the |---|---| separator; only 5-column data rows are returned."""
    rows = []
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group("cells").split("|")]
        if len(cells) != 5:
            continue
        who, referrer, description, updated, sig = cells
        if who.lower() == "who" or set(who) <= {"-", ":"}:
            continue   # header / separator
        if "@" not in who:
            continue   # not a data row
        rows.append(Row(who, referrer, description, updated, sig))
    return rows


def owner_email_from_path(path: str) -> str | None:
    base = os.path.basename(path)
    m = re.match(r"(.+)_murmur\.md$", base)
    if not m or "@" not in m.group(1):
        return None
    return m.group(1).lower()


def owner_key(rows: list[Row], owner_email: str) -> str | None:
    """The public key of the file's self-row (who==owner, empty referrer,
    valid sig). None if there is no valid signed self-row."""
    for r in rows:
        if r.who.lower() == owner_email and not r.referrer and r.has_sig:
            if r.verifies():
                p = r.sig_parts()
                return p[0] if p else None
    return None


def validate_file(path: str, base_dir: str | None) -> list[str]:
    """Return a list of violation strings for one file (empty = OK)."""
    problems: list[str] = []
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        return [f"{path}: cannot read ({e})"]

    rows = parse_rows(text)

    # R1 — every signed row must verify.
    for r in rows:
        if r.has_sig and not r.verifies():
            problems.append(
                f"{path}: INVALID signature on row for {r.who!r} "
                f"(present but does not verify — forgery or corruption)")

    # R2 — owner-key protection for db/<email>_murmur.md.
    owner_email = owner_email_from_path(path)
    if owner_email and base_dir:
        base_path = os.path.join(base_dir, path)
        if os.path.exists(base_path):
            base_text = open(base_path, encoding="utf-8").read()
            base_rows = parse_rows(base_text)
            base_owner = owner_key(base_rows, owner_email)
            if base_owner:  # file had an established owner key
                head_owner = owner_key(rows, owner_email)
                if head_owner != base_owner:
                    problems.append(
                        f"{path}: OWNER-KEY CHANGE for {owner_email!r} "
                        f"(base {base_owner[:12]}… → head "
                        f"{(head_owner or 'none')[:12]}…). Refusing: the "
                        f"signing key is the file's edit permission (G2/G3).")
    return problems


def main(argv: list[str]) -> int:
    base_dir = None
    files = []
    i = 0
    while i < len(argv):
        if argv[i] == "--base-dir":
            base_dir = argv[i + 1]
            i += 2
        else:
            files.append(argv[i])
            i += 1

    if not files:
        print("no directory files to validate")
        return 0

    all_problems = []
    for f in files:
        all_problems.extend(validate_file(f, base_dir))

    if all_problems:
        print("Directory validation FAILED:\n")
        for p in all_problems:
            print(f"  ✗ {p}")
        print(f"\n{len(all_problems)} violation(s). See ci/validate_directory.py "
              f"for the rules.")
        return 1

    print(f"Directory validation passed ({len(files)} file(s) checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
