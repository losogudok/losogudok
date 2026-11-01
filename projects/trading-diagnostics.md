[← Profile](../README.md) · [Résumé](../RESUME.md)

# Giving an AI client a coherent view of a trading system

**Personal project · Private implementation · Python / FastMCP / PostgreSQL / OKX API**

## The problem

Diagnosing a trading bot requires reconciling several sources: exchange balances and orders, database records, configuration, and logs. Copying fragments into an AI conversation makes it easy to miss context or mistake an unavailable source for an empty result.

## What I built

A local MCP server over stdio with two tools:

- **health_check** — checks that the diagnostics server is running.
- **get_trading_snapshot** — returns a structured view of exchange and database state for a trading symbol, with bounded recent orders, trades, and fills.

The snapshot includes source statuses and explainable diagnostics. A failed exchange connection can produce a partial snapshot rather than discard the database facts.

## Design decisions

| Decision | Reason |
| --- | --- |
| Read-only diagnostic tools | Inspecting a system does not require giving the AI client trading authority. |
| One structured snapshot | Keep related exchange and database facts together, with explicit source availability. |
| Separate diagnostic rules | Test interpretations of the facts independently of live exchange and database access. |
| Bounded result sections | Keep responses manageable and reduce unnecessary context. |
| Logs on stderr | Reserve stdout for the MCP protocol. |
| Explicit resource cleanup | Close exchange connections and database resources after snapshot collection. |

## Verification and limits

The implementation includes unit tests for diagnostic rules. Those tests verify rule behavior; they do not establish trading profitability or live exchange availability.

The tools do not place, cancel, amend, or synchronize orders. Runtime-only strategy state is reported as unavailable when the diagnostics process cannot access it.

The implementation remains private. This case study describes the design without publishing credentials, account information, trading records, or private source code.

## What this demonstrates

Connecting an AI client to operational data, defining useful MCP tools, separating facts from interpretation, and handling partial failures with explicit boundaries.
