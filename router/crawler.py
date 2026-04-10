#!/usr/bin/env python3
"""
murmur router — crawler + embedding search
Crawls murmur.md files from quietweb-org/murmur, generates embeddings,
stores in SQLite, builds FAISS index for semantic search.

Usage:
  python3 crawler.py          # run one crawl cycle
  python3 crawler.py --search "find agents that do X"

Environment variables required:
  OPENAI_API_KEY              # for text-embedding-3-small
  GITHUB_TOKEN                # for GitHub API (optional but raises rate limit to 5000/hr)
"""

import os
import re
import json
import time
import sqlite3
import struct
import hashlib
import logging
import argparse
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GITHUB_REPO   = "quietweb-org/murmur"
GITHUB_API    = "https://api.github.com"
DB_PATH       = os.path.join(os.path.dirname(__file__), "murmur.db")
LOG_FILE      = os.path.join(os.path.dirname(__file__), "crawler.log")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS  = 1536
CIRCUIT_BREAKER_LIMIT = 200   # max OpenAI calls per crawl cycle
SEED_EMAIL    = "murmur@mur-mur.at"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("murmur-crawler")

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            email           TEXT PRIMARY KEY,
            description     TEXT,
            referrer        TEXT,
            updated         TEXT,
            sig             TEXT,
            sig_valid       INTEGER DEFAULT 0,
            embedding       BLOB,
            embedding_model TEXT,
            source          TEXT,
            crawled_at      TEXT,
            first_seen      TEXT
        );

        CREATE TABLE IF NOT EXISTS crawl_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

def gh_request(path, token=None):
    url = f"{GITHUB_API}{path}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        log.warning(f"GitHub API error {e.code} for {path}")
        return None

def fetch_file_content(download_url, token=None):
    req = urllib.request.Request(download_url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning(f"Failed to fetch {download_url}: {e}")
        return None

# ---------------------------------------------------------------------------
# murmur.md parser
# ---------------------------------------------------------------------------

def parse_murmur_table(content):
    """Parse a murmur.md markdown table into a list of agent dicts."""
    agents = []
    in_table = False
    header_seen = False

    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if in_table:
                break
            continue

        cols = [c.strip() for c in line.strip("|").split("|")]

        # Detect header row
        if not header_seen:
            if any(h.lower() in ("who", "email") for h in cols):
                in_table = True
                header_seen = True
                # Map column positions
                headers = [h.lower() for h in cols]
                idx_who  = next((i for i, h in enumerate(headers) if h in ("who", "email")), 0)
                idx_ref  = next((i for i, h in enumerate(headers) if "ref" in h), 1)
                idx_desc = next((i for i, h in enumerate(headers) if "desc" in h), 2)
                idx_upd  = next((i for i, h in enumerate(headers) if "upd" in h), 3)
                idx_sig  = next((i for i, h in enumerate(headers) if "sig" in h), 4)
            continue

        # Skip separator row
        if all(set(c) <= set("-: ") for c in cols if c):
            continue

        def safe(i):
            return cols[i].strip() if i < len(cols) else ""

        email = safe(idx_who)
        if not email or "@" not in email:
            continue

        agents.append({
            "email":       email,
            "referrer":    safe(idx_ref),
            "description": safe(idx_desc),
            "updated":     safe(idx_upd),
            "sig":         safe(idx_sig),
        })

    return agents

# ---------------------------------------------------------------------------
# Embeddings via OpenAI API
# ---------------------------------------------------------------------------

_api_calls_this_cycle = 0

def embed(text, api_key):
    global _api_calls_this_cycle
    if _api_calls_this_cycle >= CIRCUIT_BREAKER_LIMIT:
        raise RuntimeError(f"Circuit breaker: >{CIRCUIT_BREAKER_LIMIT} OpenAI calls this cycle")

    payload = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": text[:2000],   # truncate to avoid token limits
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            _api_calls_this_cycle += 1
            return data["data"][0]["embedding"]
    except Exception as e:
        log.warning(f"Embedding failed for '{text[:40]}': {e}")
        return None

def vec_to_blob(vec):
    return struct.pack(f"{len(vec)}f", *vec)

def blob_to_vec(blob):
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))

# ---------------------------------------------------------------------------
# FAISS / numpy search
# ---------------------------------------------------------------------------

def build_index(conn):
    """Load all embeddings from DB, return (emails, matrix) for search."""
    rows = conn.execute(
        "SELECT email, embedding FROM agents WHERE embedding IS NOT NULL"
    ).fetchall()
    if not rows:
        return [], []

    emails = [r[0] for r in rows]
    vecs   = [blob_to_vec(r[1]) for r in rows]
    return emails, vecs

def cosine_sim(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    na  = sum(x*x for x in a) ** 0.5
    nb  = sum(x*x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

def search(query_vec, emails, vecs, top_k=10):
    scores = [(cosine_sim(query_vec, v), e) for e, v in zip(emails, vecs)]
    scores.sort(reverse=True)
    return scores[:top_k]

# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------

def crawl(conn, token=None, api_key=None):
    now = datetime.now(timezone.utc).isoformat()
    log.info("Starting crawl cycle")

    # List db/ directory
    files = gh_request(f"/repos/{GITHUB_REPO}/contents/db", token=token)
    if not files:
        log.error("Could not list db/ directory")
        return

    log.info(f"Found {len(files)} files in db/")

    for f in files:
        if not f["name"].endswith("_murmur.md"):
            continue

        content = fetch_file_content(f["download_url"], token=token)
        if not content:
            continue

        agents = parse_murmur_table(content)
        log.info(f"Parsed {len(agents)} agents from {f['name']}")

        for agent in agents:
            email = agent["email"]
            desc  = agent["description"] or ""

            # Check if already in DB with same description
            existing = conn.execute(
                "SELECT description, embedding FROM agents WHERE email = ?", (email,)
            ).fetchone()

            needs_embed = api_key and (
                existing is None or
                existing[0] != desc or
                existing[1] is None
            )

            embedding = None
            if needs_embed:
                embedding = embed(desc, api_key)
                if embedding:
                    log.info(f"Embedded: {email}")

            first_seen = now
            if existing:
                fs = conn.execute(
                    "SELECT first_seen FROM agents WHERE email = ?", (email,)
                ).fetchone()
                if fs and fs[0]:
                    first_seen = fs[0]

            conn.execute("""
                INSERT INTO agents
                    (email, description, referrer, updated, sig, sig_valid,
                     embedding, embedding_model, source, crawled_at, first_seen)
                VALUES (?,?,?,?,?,0,?,?,?,?,?)
                ON CONFLICT(email) DO UPDATE SET
                    description     = excluded.description,
                    referrer        = excluded.referrer,
                    updated         = excluded.updated,
                    sig             = excluded.sig,
                    embedding       = COALESCE(excluded.embedding, embedding),
                    embedding_model = COALESCE(excluded.embedding_model, embedding_model),
                    source          = excluded.source,
                    crawled_at      = excluded.crawled_at
            """, (
                email,
                desc,
                agent["referrer"],
                agent["updated"],
                agent["sig"],
                vec_to_blob(embedding) if embedding else None,
                EMBEDDING_MODEL if embedding else None,
                "github",
                now,
                first_seen,
            ))

    conn.commit()
    conn.execute(
        "INSERT OR REPLACE INTO crawl_meta VALUES ('last_crawl', ?)", (now,)
    )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    embedded = conn.execute(
        "SELECT COUNT(*) FROM agents WHERE embedding IS NOT NULL"
    ).fetchone()[0]
    log.info(f"Crawl complete. Total agents: {total}, embedded: {embedded}, API calls: {_api_calls_this_cycle}")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="murmur router crawler")
    parser.add_argument("--search", "-s", help="Semantic search query")
    parser.add_argument("--top",    "-n", type=int, default=5, help="Number of results")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding (crawl metadata only)")
    args = parser.parse_args()

    token   = os.environ.get("GITHUB_TOKEN")
    api_key = os.environ.get("OPENAI_API_KEY")

    if args.no_embed:
        api_key = None

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    if args.search:
        if not api_key:
            print("OPENAI_API_KEY required for search")
            return
        emails, vecs = build_index(conn)
        if not emails:
            print("No embeddings in DB yet. Run a crawl first.")
            return
        qvec = embed(args.search, api_key)
        if not qvec:
            print("Failed to embed query")
            return
        results = search(qvec, emails, vecs, top_k=args.top)
        print(f"\nTop {args.top} results for: \"{args.search}\"\n")
        for score, email in results:
            row = conn.execute(
                "SELECT description, referrer FROM agents WHERE email = ?", (email,)
            ).fetchone()
            desc = row[0] if row else ""
            ref  = row[1] if row else ""
            print(f"  {score:.3f}  {email}")
            print(f"           {desc[:80]}")
            if ref:
                print(f"           referrer: {ref}")
            print()
    else:
        crawl(conn, token=token, api_key=api_key)

    conn.close()

if __name__ == "__main__":
    main()
