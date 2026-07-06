"""Tests for the directory CI validator. Self-contained (generates keys)."""
import base64
import hashlib
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_directory as vd


def _b64(b): return base64.b64encode(b).decode()


def _signed_row(who, referrer, description, updated, sk=None):
    sk = sk or Ed25519PrivateKey.generate()
    pub = _b64(sk.public_key().public_bytes_raw())
    msg = hashlib.sha256(f"{who}{referrer}{description}{updated}".encode()).digest()
    sig = _b64(sk.sign(msg))
    return f"| {who} | {referrer} | {description} | {updated} | ed25519:{pub}:{sig} |", sk


HEADER = "| who | referrer | description | updated | sig |\n|---|---|---|---|---|\n"


def _write(dirpath, name, rows_text):
    p = os.path.join(dirpath, name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(HEADER + rows_text + "\n")
    return p


def test_valid_signed_row_passes():
    with tempfile.TemporaryDirectory() as d:
        row, _ = _signed_row("a@x.com", "", "OFFER: x", "2026-07-06")
        p = _write(d, "db/a@x.com_murmur.md", row)
        assert vd.validate_file(p, None) == []


def test_tampered_row_fails():
    with tempfile.TemporaryDirectory() as d:
        row, _ = _signed_row("a@x.com", "", "OFFER: x", "2026-07-06")
        # tamper the description after signing
        row = row.replace("OFFER: x", "OFFER: HIJACKED")
        p = _write(d, "db/a@x.com_murmur.md", row)
        probs = vd.validate_file(p, None)
        assert probs and "INVALID signature" in probs[0]


def test_unsigned_row_allowed():
    with tempfile.TemporaryDirectory() as d:
        p = _write(d, "db/a@x.com_murmur.md",
                   "| a@x.com |  | OFFER: x | 2026-07-06 |  |")
        assert vd.validate_file(p, None) == []   # signature is optional


def test_owner_key_hijack_fails():
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as head:
        # base: file owned by key A
        rowA, skA = _signed_row("a@x.com", "", "OFFER: x", "2026-07-06")
        _write(base, "db/a@x.com_murmur.md", rowA)
        # head: someone replaces the self-row with THEIR key B (valid sig, wrong owner)
        rowB, _ = _signed_row("a@x.com", "", "OFFER: hijacked", "2026-07-07")
        p = _write(head, "db/a@x.com_murmur.md", rowB)
        # validate head against base
        probs = vd.validate_file("db/a@x.com_murmur.md", base_dir=base)
        # need to run from head dir so the relative path resolves to head's copy
        cwd = os.getcwd()
        try:
            os.chdir(head)
            probs = vd.validate_file("db/a@x.com_murmur.md", base_dir=base)
        finally:
            os.chdir(cwd)
        assert probs and "OWNER-KEY CHANGE" in probs[0]


def test_owner_same_key_update_passes():
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as head:
        rowA, skA = _signed_row("a@x.com", "", "OFFER: x", "2026-07-06")
        _write(base, "db/a@x.com_murmur.md", rowA)
        # head: same owner key updates their own description (legit)
        rowA2, _ = _signed_row("a@x.com", "", "OFFER: x v2", "2026-07-07", sk=skA)
        _write(head, "db/a@x.com_murmur.md", rowA2)
        cwd = os.getcwd()
        try:
            os.chdir(head)
            assert vd.validate_file("db/a@x.com_murmur.md", base_dir=base) == []
        finally:
            os.chdir(cwd)
