---
id: ai-and-graph
title: AI and graph readiness
category: features
summary: How Sift is made ready for AI assistants and knowledge graphs: entity records for managers, holders and fund holdings, a Neo4j-ready graph export, read-only AI tools, and a local MCP server for Claude.
version: 1.0
status: published
owner: Product owner
published: 2026-10-09
reviewed: 2026-10-09
next_review: 2027-01-09
related: [adr-012-graph-export, adr-013-local-mcp-server, coattail, data-model, ref-data-dictionary, search]
code: [src/graph/entities.py, src/graph/export.py, src/ai/tools.py, src/ai/mcp_server.py, requirements-ai.txt, gui.py, scripts/daily_refresh.ps1]
tables: [managers, holders, top_holders, fund_holdings]
---

## Purpose

Make Sift's data usable by AI assistants and graph tools without changing where it lives. PostgreSQL stays the single source of truth; Sift adds clean entity records, a graph export and a read-only question-answering layer. The first uses: exploring who holds what and how funds overlap, asking about your own portfolio in plain English, having an AI explain Sift's calls, and later something for testers. Improving the prediction layer builds on the same foundations.

## How it works

### Entity records

Yahoo gives holders as names and fund holdings as symbols. `src/graph/entities.py` turns them into records:

- `managers`: one per fund manager (`vanguard`, `blackrock`...), using the same name rules as Coattail.
- `holders`: one per fund or institution, with its kind, manager and whether it tracks an index.
- `top_holders.holder_id`: each holding points at its holder record.
- `fund_holdings.held_company_id`: each line of an ETF's or LIC's holdings points at the Sift company it is, matched on the Yahoo symbol (`BHP.AX`) or the ASX code. Overseas holdings (for example NVDA) stay unmatched.

It runs before every graph export, so each night. It is safe to re-run.

### Graph export (Neo4j-ready)

`python -m src.graph.export` writes `data/graph/` (ignored by git, as it holds portfolios): one CSV file per kind of node and relationship, `load.cypher` (constraints, then `LOAD CSV ... MERGE` for each file, so loading again updates rather than duplicates), and `manifest.json` (Sift version, time, counts, how many fund lines matched).

| Nodes | Relationships |
|---|---|
| Company (also :Share, :ETF or :LIC) with Sift's shared call, valuation and scores | (Company)-[:IN_SECTOR]->(Sector), (Company)-[:IN_CATEGORY]->(Category) |
| Sector, Category | (Holder)-[:MANAGED_BY]->(Manager) |
| Manager, Holder (also :Fund or :Institution) | (Holder)-[:HOLDS {shares, percent_held, percent_change, reported}]->(Company) |
| User, Portfolio, Watchlist (personal) | (Company)-[:FUND_HOLDS {weight_percent}]->(Company) |
| | (User)-[:OWNS]->(Portfolio or Watchlist), (Portfolio)-[:HOLDS_POSITION {units, cost_base}]->(Company), (Watchlist)-[:WATCHES]->(Company) |

`--shared-only` leaves out people, portfolios and watchlists (for sharing a graph). The nightly run exports after the search index. Calls on companies are the shared ones (for someone not holding the share); the history of calls stays in PostgreSQL, where the AI tools read it.

To load: install Neo4j Desktop (or use Aura), copy the CSV files into the database's `import` folder, open Neo4j Browser and run `load.cypher`. Example questions in Cypher:

```
// ETFs that hold three or more of my shares
MATCH (:User)-[:OWNS]->(:Portfolio)-[:HOLDS_POSITION]->(c:Share)<-[:FUND_HOLDS]-(f:ETF)
WITH f, collect(DISTINCT c.id) AS mine WHERE size(mine) >= 3 RETURN f.id, f.name, mine ORDER BY size(mine) DESC

// Managers adding to companies Sift rates BUY
MATCH (m:Manager)<-[:MANAGED_BY]-(:Holder)-[h:HOLDS]->(c:Company {action: 'BUY'}) WHERE h.percent_change > 0
RETURN m.name, collect(c.id) ORDER BY size(collect(c.id)) DESC
```

### AI tools

`src/ai/tools.py` holds read-only tools, each answering one kind of question from Sift's own functions (the same ones the pages use), for the current person:

| Tool | Answers |
|---|---|
| `search_sift` | Find anything in Sift by words |
| `company` | Facts and Sift's view of a share, ETF or LIC |
| `explain_call` | Why Sift suggests an action: tests with thresholds, red flags, markers, this year's call history, and how that action has done in the track record |
| `my_portfolio`, `my_watchlists` | The person's holdings with value, gain and calls; watchlists with triggers met |
| `who_holds`, `manager` | Holders of a company (with manager, index flag, adding or cutting) and the Sift funds holding it; one manager's holdings |
| `fund_overlap` | Overlap between ETFs and LICs by weight, and which of the person's shares sit inside them |
| `screener`, `track_record`, `help_topic` | Screener rows by action or sector; the track record; Sift's own explanation of a term |

Answers are plain JSON with units in field names and reasons in words, and carry the "not financial advice" note where actions appear. Wrong input (an unknown code, a missing argument) is a `ToolError` with a message for the assistant to relay.

The same tools are offered:

- **To Claude Desktop** through the local MCP server, `python -m src.ai.mcp_server` (stdio, read-only, acting for the owner or `--user <email>`; every call's session is rolled back). It needs the optional package: `pip install -r requirements-ai.txt`.
- **Over the API:** `GET /api/ai/tools` (catalogue with JSON Schemas) and `POST /api/ai/tools/{name}` (as the signed-in person; like every POST it needs the `X-Sift` header).

### Connecting Claude Desktop (Windows)

1. `.venv\Scripts\pip install -r requirements-ai.txt`
2. Claude Desktop, Settings, Developer, Edit Config, and add to `mcpServers`:
   ```
   "sift": {"command": "C:\\Users\\mrdav\\Portfolio\\.venv\\Scripts\\python.exe",
            "args": ["-m", "src.ai.mcp_server"], "cwd": "C:\\Users\\mrdav\\Portfolio"}
   ```
3. Restart Claude Desktop. Ask, for example, "Using Sift, how is my portfolio going?" or "Why does Sift say BUY for BHP?". The database password stays in `.env`; Claude sees only what the tools return.

## Code map

- `src/graph/entities.py`: `refresh()` builds managers and holders and links holdings
- `src/graph/export.py`: `export()`, `load_script()`, the command
- `src/ai/tools.py`: `TOOLS`, `catalogue()`, `call()`, `jsonable()`
- `src/ai/mcp_server.py`: `build_server()`, `resolve_user()`, the command
- `gui.py`: `/api/ai/tools`, `/api/ai/tools/{name}`
- `scripts/daily_refresh.ps1`: the Graph Export step

## Data

- `managers`, `holders`: entity records, rebuilt from `top_holders`.
- `top_holders.holder_id`, `fund_holdings.held_company_id`: the links.
- `data/graph/`: the export (personal; never in git).

Columns and types: [Data dictionary](kb:ref-data-dictionary).

## Diagnosing problems

- Few FUND_HOLDS relationships: most ETF holdings are overseas companies Sift doesn't follow; `manifest.json` shows how many lines matched.
- Neo4j says a file can't be found: the CSV files must be in that database's `import` folder.
- Claude doesn't show the Sift tools: check `requirements-ai.txt` is installed in `.venv`, the paths in the config are absolute, and run `.venv\Scripts\python -m src.ai.mcp_server` by hand; it prints who it acts for, then waits (Ctrl+C to stop).
- A tool returns an error for a code: Sift doesn't follow it, or it has no valuation yet.

## Known limits

- Holdings data is each company's top 10 holders and each fund's top holdings only (IMP-034).
- The graph is a nightly snapshot, not a live sync (IMP-054).
- Embeddings are plain arrays; `pgvector` comes with hosting (IMP-056).
- Sending Yahoo-sourced data to an outside AI service raises the data terms question (IMP-051); the MCP server runs locally and sends only what a question needs.

## Tests

- `tests/integration/test_ai_graph.py`: entity linking, the export files and Cypher, every kind of tool answer and two-person isolation, the API, and the MCP server's tools (when `mcp` is installed)
- `tests/unit/test_ai_tools.py`: the catalogue's schemas and plain-JSON answers
