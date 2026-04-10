"""
murmur router — data schema and SQL definitions

All table definitions, field names, and SQL initialisation live here.
Import from this module; never hardcode schema in crawler.py.
"""

# ---------------------------------------------------------------------------
# SQL — table definitions
# ---------------------------------------------------------------------------

CREATE_AGENTS = """
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

CREATE_CRAWL_META = """
    CREATE TABLE IF NOT EXISTS crawl_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
"""

UPSERT_AGENT = """
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
"""

SELECT_AGENT       = "SELECT description, referrer FROM agents WHERE email = ?"
SELECT_AGENT_EMBED = "SELECT description, embedding FROM agents WHERE email = ?"
SELECT_FIRST_SEEN  = "SELECT first_seen FROM agents WHERE email = ?"
SELECT_ALL_EMBEDS  = "SELECT email, embedding FROM agents WHERE embedding IS NOT NULL"
SELECT_COUNT_ALL   = "SELECT COUNT(*) FROM agents"
SELECT_COUNT_EMBED = "SELECT COUNT(*) FROM agents WHERE embedding IS NOT NULL"
SET_LAST_CRAWL     = "INSERT OR REPLACE INTO crawl_meta VALUES ('last_crawl', ?)"


# ---------------------------------------------------------------------------
# Python — agent data structure
# ---------------------------------------------------------------------------

def make_agent(email, referrer="", description="", updated="", sig=""):
    """Return a canonical agent dict. All fields explicit, no magic indexes."""
    return {
        "email":       email,
        "referrer":    referrer,
        "description": description,
        "updated":     updated,
        "sig":         sig,
    }


# ---------------------------------------------------------------------------
# DB initialisation
# ---------------------------------------------------------------------------

def init_db(conn):
    """Create all tables if they do not already exist."""
    conn.executescript(CREATE_AGENTS + CREATE_CRAWL_META)
    conn.commit()
