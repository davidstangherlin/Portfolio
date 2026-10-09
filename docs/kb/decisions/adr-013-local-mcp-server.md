---
id: adr-013-local-mcp-server
title: Decision: a local, read-only MCP server for AI assistants
category: decisions
summary: Why AI assistants reach Sift through a local, read-only MCP server built on a shared tool layer, rather than direct database access or a hosted AI feature.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-04-09
decision_status: accepted
related: [ai-and-graph, adr-007-owner-scoping, adr-012-graph-export]
code: [src/ai/tools.py, src/ai/mcp_server.py, requirements-ai.txt]
---

## Status

Accepted, 2026-10-09.

## Context

The owner wants to ask questions of their portfolio in plain English and have an AI explain Sift's calls, with testers to follow. The answers must match what Sift's pages show and respect whose data is whose.

## Decision

A tool layer (`src/ai/tools.py`) of read-only tools built on Sift's own functions, each scoped to one person. Offered to Claude Desktop through a local MCP server over stdio, acting for the owner (or a named account), with every call rolled back; and over the API for later use. The MCP package is optional (`requirements-ai.txt`).

## Options considered

- **Give the assistant SQL access:** flexible, but bypasses the rules (shared versus personal calls, owner scoping) and can read anything.
- **A hosted AI feature inside Sift (calling an AI API):** smooth for testers, but a cost, an API key and data sent out on every question.
- **No connector yet:** nothing to maintain, but nothing to learn from either.

## Consequences

Answers come from the same code as the pages, so they agree. Nothing is written. Data leaves the PC only when the person asks Claude a question, and only what the tools return. Adding a question means adding a tool.

## Revisit when

Testers need it (a hosted, signed-in version: Phase 3 or later), or the AI should act (for example draft a watchlist), which needs write tools with confirmation.
