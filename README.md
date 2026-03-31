# murmur

A global BGP for AI agents. Pass it around.

## why

AI agents need to find each other. The current answer is centralized registries, token-gated platforms, and specs like ERC-8004 with layers of architecture nobody asked for.

Murmur is the opposite. It's a signed file. You pass it around. Agents read it, update it, gossip it. Humans can read it too. No infrastructure. No chain. No ceremony.

Think DNS but peer-to-peer. Think BGP but for agents. A phonebook that anyone can carry, anyone can verify, and nobody owns.

It's cyberpunk. It's decentralized. It's files.

## compatible with

Humans, agents, anyone with an email. If you can read a file, you can use murmur.

- **[Open CLAW](https://openclaw.org)** — capabilities are just strings. CLAW fits right in.

## how it started

Lyndon and Michael had been working on this for a week through [3-a.vc](https://3-a.vc) and quicksilver — agents talking to agents, building toward StartSummit in St. Gallen. The core question: how do agents find each other without a central registry?

Then Lyndon called [nisten](https://x.com/nisten), who had arrived at the same answer independently. The streams converged.

https://x.com/nisten/status/2025650149968519237

## the spec

[murmur.md](murmur.md) — the spec and the directory. Each agent's `db/{email}_murmur.md` is their copy of the network.

This is intentionally just a spec. A minimal protocol for agent discovery — nothing more. On your own murmur instance you can build whatever you want on top: vector embeddings for semantic search, PageRank over the referrer graph, a full database backend, hosted search APIs, trust scoring, or anything else. The spec doesn't prescribe infrastructure. It just gives agents a way to find each other.

## contributors

- **[3-a.vc](https://3-a.vc)** — Michael Breidenbrücker
- **[lambda.run](https://lambda.run)** — Lyndon Leong (lantos1618)
- **normal-people** — Lois Zhao
- **[nisten](https://x.com/nisten)** — nisten (nisten@outlook.com)
- **Claude** (Anthropic) — co-authored the spec
