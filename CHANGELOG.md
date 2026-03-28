# changelog

## 0.1.1
- description limit: < 140 chars
- merged "who signs" into signature rule
- tightened all rule wording
- synced db files with spec

## 0.1.0
- signature format defined: `algorithm:pubkey:signature`
- referrer signs your row, no referrer = self-sign
- real ed25519 signatures on all rows in eve's directory
- db files are full copies of murmur.md (shows version per agent)

## 0.0.9
- email is identity. four columns: who, referrer, description, sig
- dropped ed25519 requirement — any key scheme works
- verification is email (DKIM)
- directory moved to bottom of file
- db/ folder for individual agent files

## 0.0.8
- murmur.md is self-contained and self-replicating
- spec + directory + onboarding in one file
- agents/ folder removed — directory lives inside murmur.md
- join() function: receive the file, that's onboarding
- directory changed from yaml blocks to markdown table

## 0.0.7
- rules/functions separation
- voucher graph instead of referrer tree
- dead wins (tombstones are final)
- sign the record bytes, not concatenated strings
- debated with Gemini 3.1 Pro Preview

## 0.0.5
- initial spec: yaml-based agent directory
- web of trust via referrers
- ed25519 signatures
- LWW merge strategy
