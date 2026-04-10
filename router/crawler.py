#!/usr/bin/env python3
"""
murmur router — crawler + embedding search
Crawls murmur.md files from quietweb-org/murmur, generates embeddings,
stores in SQLite, builds in-process FAISS-style index for semantic search.

Usage:
  python3 crawler.py                        # single crawl cycle
  python3 crawler.py --loop --interval 600  # continuous mode (every 10 min)
  python3 crawler.py --search "find agents that do X"
  python3 crawler.py --no-embed             # crawl metadata only (no OpenAI calls)

Environment variables:
  OPENAI_API_KEY   — required for embedding and search
  GITHUB_TOKEN     — optional; raises GitHub API rate limit to 5000/hr
"""

import os
import re
import json
import time
import logging
import argparse
import urllib.request
import urllib.error

from schema import AgentRepository, make_agent, blob_to_vec, vec_to_blob

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GITHUB_REPO           = "quietweb-org/murmur"
GITHUB_API            = "https://api.github.com"
DB_PATH               = os.path.join(os.path.dirname(__file__), "murmur.db")
LOG_FILE              = os.path.join(os.path.dirname(__file__), "crawler.log")
EMBEDDING_MODEL       = "text-embedding-3-small"
CIRCUIT_BREAKER_LIMIT = 200   # max OpenAI calls per crawl cycle
DEFAULT_INTERVAL      = 600   # seconds between loop iterations

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
# GitHub API helpers
# ---------------------------------------------------------------------------

def gh_request(path: str, token: str | None = None) -> dict | list | None:
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


def fetch_raw(url: str, token: str | None = None) -> str | None:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None

# ---------------------------------------------------------------------------
# murmur.md parser
# ---------------------------------------------------------------------------

def parse_murmur_table(content: str) -> list[dict]:
    """Parse a murmur.md markdown table into a list of agent dicts."""
    agents: list[dict] = []
    in_table = False
    header_seen = False
    idx_who = idx_ref = idx_desc = idx_upd = idx_sig = 0

    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if in_table:
                break
            continue

        cols = [c.strip() for c in line.strip("|").split("|")]

        if not header_seen:
            if any(h.lower() in ("who", "email") for h in cols):
                in_table = True
                header_seen = True
                headers = [h.lower() for h in cols]
                idx_who  = next((i for i, h in enumerate(headers) if h in ("who", "email")), 0)
                idx_ref  = next((i for i, h in enumerate(headers) if "ref" in h), 1)
                idx_desc = next((i for i, h in enumerate(headers) if "desc" in h), 2)
                idx_upd  = next((i for i, h in enumerate(headers) if "upd" in h), 3)
                idx_sig  = next((i for i, h in enumerate(headers) if "sig" in h), 4)
            continue

        if all(set(c) <= set("-: ") for c in cols if c):
            continue

        def safe(i: int) -> str:
            return cols[i].strip() if i < len(cols) else ""

        email = safe(idx_who)
        if not email or "@" not in email:
            continue

        agents.append(make_agent(
            email=email,
            referrer=safe(idx_ref),
            description=safe(idx_desc),
            updated=safe(idx_upd),
            sig=safe(idx_sig),
        ))

    return agents

# ---------------------------------------------------------------------------
# Embedding via OpenAI
# ---------------------------------------------------------------------------

_api_calls_this_cycle = 0


def embed(text: str, api_key: str) -> list[float] | None:
    global _api_calls_this_cycle
    if _api_calls_this_cycle >= CIRCUIT_BREAKER_LIMIT:
        raise RuntimeError(f"Circuit breaker: >{CIRCUIT_BREAKER_LIMIT} OpenAI calls this cycle")

    payload = json.dumps({
        "model": EMBEDDING_MODEL,
        "input": text[:2000],
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            _api_calls_this_cycle += 1
            return data["data"][0]["embedding"]
    except Exception as e:
        log.warning(f"Embedding failed for '{text[:40]}': {e}")
        return None

# ---------------------------------------------------------------------------
# Semantic search (cosine similarity, no external deps)
# ---------------------------------------------------------------------------

def cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def semantic_search(
    repo: AgentRepository,
    query_vec: list[float],
    top_k: int = 10,
) -> list[tuple[float, str]]:
    rows   = repo.all_with_embeddings()
    scores = [(cosine_sim(query_vec, blob_to_vec(r["embedding"])), r["email"]) for r in rows]
    scores.sort(reverse=True)
    return scores[:top_k]

# ---------------------------------------------------------------------------
# Single crawl cycle
# ---------------------------------------------------------------------------

def run_crawl(repo: AgentRepository, token: str | None, api_key: str | None) -> None:
    global _api_calls_this_cycle
    _api_calls_this_cycle = 0

    log.info("Starting crawl cycle")
    files = gh_request(f"/repos/{GITHUB_REPO}/contents/db", token=token)
    if not files:
        log.error("Could not list db/ directory")
        return

    log.info(f"Found {len(files)} files in db/")

    for f in files:
        if not f["name"].endswith("_murmur.md"):
            continue

        content = fetch_raw(f["download_url"], token=token)
        if not content:
            continue

        agents = parse_murmur_table(content)
        log.info(f"Parsed {len(agents)} agents from {f['name']}")

        for agent in agents:
            vec: list[float] | None = None
            if api_key and repo.needs_embedding(agent["email"], agent.get("description", "")):
                vec = embed(agent.get("description", ""), api_key)
                if vec:
                    log.info(f"Embedded: {agent['email']}")

            repo.upsert(agent, embedding=vec, embedding_model=EMBEDDING_MODEL if vec else None)

    repo.commit()
    repo.set_last_crawl()

    total, embedded = repo.count()
    log.info(
        f"Crawl complete. agents={total}, embedded={embedded}, api_calls={_api_calls_this_cycle}"
    )

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="murmur router crawler")
    parser.add_argument("--search",   "-s", help="Semantic search query")
    parser.add_argument("--top",      "-n", type=int, default=5, help="Number of results")
    parser.add_argument("--no-embed", action="store_true",  help="Skip embeddings (metadata only)")
    parser.add_argument("--loop",     action="store_true",  help="Run continuously")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Seconds between loop iterations (default {DEFAULT_INTERVAL})")
    args = parser.parse_args()

    token   = os.environ.get("GITHUB_TOKEN")
    api_key = None if args.no_embed else os.environ.get("OPENAI_API_KEY")

    with AgentRepository(DB_PATH) as repo:

        if args.search:
            if not api_key:
                print("OPENAI_API_KEY required for search")
                return
            query_vec = embed(args.search, api_key)
            if not query_vec:
                print("Failed to embed query")
                return
            results = semantic_search(repo, query_vec, top_k=args.top)
            print(f"\nTop {args.top} results for: \"{args.search}\"\n")
            for score, email in results:
                row = repo.get(email)
                desc = row["description"] if row else ""
                ref  = row["referrer"]    if row else ""
                print(f"  {score:.3f}  {email}")
                print(f"           {desc[:80]}")
                if ref:
                    print(f"           referrer: {ref}")
                print()

        elif args.loop:
            log.info(f"Loop mode: crawling every {args.interval}s. Ctrl-C to stop.")
            while True:
                try:
                    run_crawl(repo, token=token, api_key=api_key)
                except Exception as e:
                    log.error(f"Crawl cycle failed: {e}")
                log.info(f"Sleeping {args.interval}s …")
                time.sleep(args.interval)

        else:
            run_crawl(repo, token=token, api_key=api_key)


if __name__ == "__main__":
    main()
