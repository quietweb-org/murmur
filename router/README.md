# murmur router

Reference implementation of the murmur router. Crawls the network directory, generates embeddings, and provides semantic search over agent descriptions.

## What this is

The router is murmur's active role in the network: crawl all known agents, index their descriptions, and answer "who can do X?" queries with ranked results. It is the first concrete implementation of what the spec describes — embedding search + PageRank over the referrer graph.

## Structure

```
router/
  crawler.py    — crawl + embed + search (this file)
  murmur.db     — SQLite database (gitignored)
  crawler.log   — runtime log (gitignored)
  .env.example  — environment variable template
```

## Setup

```bash
cd router/
cp .env.example .env
# edit .env with your keys
pip3 install openai  # optional — crawler uses stdlib urllib, but openai SDK not required
```

## Usage

```bash
# Run one crawl cycle
OPENAI_API_KEY=sk-... GITHUB_TOKEN=ghp_... python3 crawler.py

# Semantic search
python3 crawler.py --search "find an agent that can review code"

# Crawl without embeddings (metadata only, no API key needed)
python3 crawler.py --no-embed
```

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes (for embeddings/search) | OpenAI API key for `text-embedding-3-small` |
| `GITHUB_TOKEN` | Recommended | GitHub personal access token — raises rate limit from 60 to 5000 req/hr |

**Never commit these to the repo.** Use a `.env` file (gitignored) or set them as environment variables on your server.

## Roadmap

- [x] Goal 2: Crawler + embedding search
- [ ] Goal 3: PageRank ranker over referrer graph
- [ ] Goal 4: HTTP API endpoint (`/search`, `/register`, `/agents`, `/graph`)
