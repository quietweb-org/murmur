"""
murmur router — data schema, SQL definitions, and repository layer

All table definitions, field names, SQL, and DB access live here.
Import from this module; never hardcode schema or queries in crawler.py.
"""

import sqlite3
import struct
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# SQL — table definitions
# ---------------------------------------------------------------------------

_CREATE_AGENTS = """
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
"""

_CREATE_CRAWL_META = """
    CREATE TABLE IF NOT EXISTS crawl_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
"""


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def vec_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def blob_to_vec(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def make_agent(email, referrer="", description="", updated="", sig="") -> dict:
    """Return a canonical agent dict. All fields explicit, no magic indexes."""
    return {
        "email":       email,
        "referrer":    referrer,
        "description": description,
        "updated":     updated,
        "sig":         sig,
    }


# ---------------------------------------------------------------------------
# Repository — all DB access goes through here
# ---------------------------------------------------------------------------

class AgentRepository:
    """
    Single access point for all agent and crawl-meta persistence.
    Owns the connection; call close() when done.
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(_CREATE_AGENTS + _CREATE_CRAWL_META)
        self.conn.commit()

    # --- agents ---

    def upsert(self, agent: dict, embedding: list[float] | None = None,
               embedding_model: str | None = None, source: str = "github") -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get(agent["email"])
        first_seen = existing["first_seen"] if existing and existing["first_seen"] else now

        self.conn.execute("""
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
            agent["email"],
            agent.get("description", ""),
            agent.get("referrer", ""),
            agent.get("updated", ""),
            agent.get("sig", ""),
            vec_to_blob(embedding) if embedding else None,
            embedding_model,
            source,
            now,
            first_seen,
        ))

    def get(self, email: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM agents WHERE email = ?", (email,)
        ).fetchone()

    def needs_embedding(self, email: str, description: str) -> bool:
        row = self.get(email)
        if row is None:
            return True
        return row["description"] != description or row["embedding"] is None

    def all_with_embeddings(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT email, embedding FROM agents WHERE embedding IS NOT NULL"
        ).fetchall()

    def count(self) -> tuple[int, int]:
        total    = self.conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        embedded = self.conn.execute(
            "SELECT COUNT(*) FROM agents WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        return total, embedded

    def commit(self):
        self.conn.commit()

    # --- crawl meta ---

    def set_last_crawl(self, ts: str | None = None) -> None:
        ts = ts or datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO crawl_meta VALUES ('last_crawl', ?)", (ts,)
        )
        self.conn.commit()

    def get_last_crawl(self) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM crawl_meta WHERE key = 'last_crawl'"
        ).fetchone()
        return row["value"] if row else None

    # --- lifecycle ---

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
