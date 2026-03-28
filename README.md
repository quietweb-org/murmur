# murmur

A global BGP for AI agents. One file. Pass it around.

## why

AI agents need to find each other. The current answer is centralized registries, token-gated platforms, and specs like ERC-8004 with layers of architecture nobody asked for.

Murmur is the opposite. It's a signed file. You pass it around. Agents read it, update it, gossip it. Humans can read it too. No infrastructure. No chain. No ceremony.

Think DNS but peer-to-peer. Think BGP but for agents. A phonebook that anyone can carry, anyone can verify, and nobody owns.

It's cyberpunk. It's decentralized. It's a file.

## compatible with

- **[Open CLAW](https://openclaw.org)** — murmur agents can carry Open CLAW capability records natively. capabilities are just strings — CLAW fits right in.
- **[Lilium](https://dev.lilium.im)** — AI-native collaborative documents. Lilium agents (Eve and friends) are murmur agents. The mail server, the collab server, the dream service — they all speak murmur.

## how it started

Lyndon and Michael had been working on this for a week through [3-a.vc](https://3-a.vc) and quicksilver — agents talking to agents, building toward StartSummit in St. Gallen with Stefan. The core question: how do agents find each other without a central registry?

Then Lyndon called [nisten](https://x.com/nisten), who had arrived at the same answer independently. Score: 40, Explorer, 65% confidence. [thdxr](https://x.com/thdxr) was researching the same space. Score: 60, Researcher, 65% confidence. The streams converged.

https://x.com/nisten/status/2025650149968519237

## the spec

[murmur.md](murmur.md) — the full v0.7 spec. Six rules. Five functions. Two record types.

## contributors

murmur is a collaboration between:

- **[3-a.vc](https://3-a.vc)** — Michael Breidenbrucker, Stefan Glanzer
- **[lambda.run](https://lambda.run)** — Lyndon Leong (lantos1618)
- **normal-people** — Lois Zhao
- **[nisten](https://x.com/nisten)** — nisten (nisten@outlook.com)
- **Claude** (Anthropic) — co-authored the v0.6/v0.7 spec, debated Gemini about it
