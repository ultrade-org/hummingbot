# Ultrade PMM Liquidity Roadmap

## Current Branch Status And Revised Sequence

### Status
- This branch has working connector-level support for Ultrade spot bulk order creation and cancellation.
- The current public Ultrade SDK exposes single order create/cancel and bulk spot create/cancel, but does not expose bulk replace.
- Bulk replace exists in the upcoming perps-platform SDK line, which also includes spot trading changes. That means replace work should be developed after the connector has been migrated to the newer SDK/API surface.
- Live testnet spot testing used the secure API path with higher rate limits. Perps are not available on live testnet yet, so the perps SDK migration and replace work should target the Ultrade dev server.

### Near-Term Goals
1. Preserve the known-working spot order-management behavior:
   - single order create/cancel fallback;
   - bulk spot create/cancel as the default fast path;
   - clean fallback when bulk endpoints are unavailable or rejected.
2. Upgrade this Hummingbot branch to the latest desired Hummingbot base.
3. Verify the upgraded branch still supports spot single and bulk order management against testnet.
4. Migrate from the current main Ultrade SDK to the upcoming perps SDK version.
5. Adapt the connector to any spot API/schema changes introduced by the perps SDK.
6. Add configurable order-management mode selection:
   - `single`;
   - `bulk`;
   - `bulk_replace`.
7. Implement and test bulk replace against the dev server once the perps SDK/API surface is in place.

### Recommended Work Order
1. **Hummingbot upgrade**
   - Rebase or port the current Ultrade connector changes onto the latest target Hummingbot version.
   - Keep the connector behavior unchanged during this step except where compatibility fixes are required.
   - Run compile/import checks and a spot smoke test.
2. **Spot regression verification**
   - Confirm single order mode still creates and cancels orders.
   - Confirm bulk mode still batches create and cancel operations.
   - Confirm stale or stuck orders are not assumed to be tracked unless Hummingbot created or restored them.
3. **Perps SDK migration**
   - Replace the current SDK dependency with the perps SDK version.
   - Audit spot method names, payloads, response shapes, signing behavior, auth, and websocket events.
   - Point connector configuration at the Ultrade dev server for perps-era testing.
4. **Order-management mode selector**
   - Replace the current boolean bulk flag with an explicit connector-level mode.
   - Keep compatibility with existing configs that still use `use_bulk_order_endpoints`.
   - Default to `bulk` for spot once verified.
5. **Bulk replace implementation**
   - Add SDK-backed bulk replace calls.
   - Map replace responses back into Hummingbot order tracking.
   - Add fallback to `bulk` or `single` when replace is unsupported, partially rejected, or circuit-broken.
   - Evaluate whether connector-level queueing is enough, or whether PMM/uPMM needs a strategy-level replace hook.

## 1. Stable PMM Configuration For Healthy Order Books

### Objectives
- Keep the AMM-style book populated during price updates or fills so takers always see depth on both sides.
- Minimise quote churn that causes gaps or unnecessary fees, while still letting the strategy react when the market genuinely moves.
- Provide a repeatable configuration recipe that listing partners can reuse for freshly listed tokens.

### Observed Behaviour (Current Defaults)
- `order_refresh_tolerance_pct = -1` forces PMM to cancel all live quotes whenever the proposal changes; the book is empty between cancel/replace cycles.
- `filled_order_delay` postpones new orders on the filled side, so liquidity disappears for up to the delay plus cancel round trip.
- Waiting for cancel confirmations (`should_wait_order_cancel_confirmation = True`) blocks the creation of new quotes until every cancel finishes.

### Configuration Strategy
1. **Keep orders in-market longer**
   - Set `order_refresh_tolerance_pct` to **0.5% – 2%** depending on volatility. Quotes within the band persist, while stale quotes are refreshed.
   - Increase `order_refresh_time` to **20–30s** so the strategy only evaluates full refreshes periodically instead of every tick.
   - Ensure `max_order_age` remains below 15–30 minutes to recycle genuinely old quotes.
2. **Instant recovery after fills**
   - Reduce `filled_order_delay` to **0–2s** so the strategy refills the consumed layer immediately.
   - Disable cancel blocking by setting `should_wait_order_cancel_confirmation = False` to allow new quotes while cancel acknowledgements arrive.
3. **Buffer liquidity with hanging orders**
   - Enable `hanging_orders_enabled`.
   - Set `hanging_orders_cancel_pct` between **5–10%** so hanging orders remain until price moves substantially, preserving a spine of liquidity.
4. **Layered depth and inventory control**
   - Use `order_levels >= 4` with `order_level_spread` of **0.1–0.2%** to add depth as you move away from mid-price.
   - Consider `inventory_skew_enabled = True` with a modest `inventory_range_multiplier` (e.g. 0.2) to bias replenishment towards the thinner side.
5. **Risk management**
   - Define `minimum_spread` to avoid listing quotes that are too close to mid.
   - Monitor balances and set `order_refresh_tolerance_pct` lower if inventory churn becomes excessive.

### Implementation & Rollout Plan
1. Draft configuration template under `conf/strategies`, documenting each parameter and recommended ranges.
2. Test with simulated volatility and live dry-run:
   - Record order-book snapshots, order counts, average refresh latency.
   - Track inventory drift and net PnL.
3. Tune tolerance and delay values per market volatility band (low/medium/high).
4. Publish guidance for liquidity partners, including monitoring dashboards (spread coverage, order uptime).
5. Create automation script to apply the template and set up alerts (e.g. minimum live orders per side).

## 2. Ultrade PMM (uPMM) With Bulk Replace

### Objectives
- Eliminate flat-book windows by replacing orders in-place once Ultrade’s paired `bulk_replace` endpoint is available.
- Minimise API workload (and throttling risk) by diffing proposals against live orders and sending replacements instead of cancel+create cycles.
- Preserve compatibility with the stock PMM strategy and connectors that lack replace support.

### Proposed Architecture
1. **Connector Capability**
   - Extend `UltradeExchange` with `supports_bulk_replace` detection and a `bulk_replace_orders` method that accepts `(existing_order_id, signed_payload)` tuples.
   - Maintain backwards compatibility by falling back to existing cancel/create when replace is unavailable or fails.
2. **Strategy Derivative (Ultrade_PMM)**
   - Derive `UltradePureMarketMakingStrategy` from PMM, overriding the order management loop.
   - Build a diff engine that compares the current proposal to the active order book:
     - Matched price/size pairs → call bulk replace with updated parameters.
     - Surplus live orders → cancel or convert to hanging orders.
     - New proposal entries with no live counterpart → submit as creates.
   - Reuse existing modifiers (inventory skew, hanging orders) so behaviour mirrors PMM aside from execution path.
3. **Task Scheduler**
   - Introduce a two-phase cycle per tick:
     1. Generate proposal + diff into `replacements`, `creates`, `cancels`.
     2. Dispatch replacements in chunks (respecting API batch size), then handle creates and cancels concurrently.
   - Maintain safeguards for tolerance bands, minimum spread, and inventory controls.

### Work Breakdown
1. **Research & Design**
   - Document replace payload schema and signing requirements.
   - Define diff heuristics (price rounding, partial size adjustments).
   - Plan telemetry (latency, replace success rate, order coverage).
2. **Connector Enhancements**
   - Implement replace client call + capability flag on `UltradeClient`.
   - Add circuit breaker: disable replace and revert to sequential mode on error spikes.
3. **Strategy Implementation**
   - Fork PMM core into `ultrade_pmm_strategy`.
   - Implement proposal diff + batch replace orchestration.
   - Add configuration options (replace batching, tolerance for reusing orders).
4. **Testing**
   - Unit tests for diff calculator and fallback logic.
   - Integration tests against a mocked Ultrade API (success, partial success, failure).
   - Dry-run with live market data capturing book continuity metrics.
5. **Rollout**
   - Provide migration guide summarising configuration differences vs standard PMM.
   - Monitor production metrics (order uptime, spread coverage, replace latency).

### Open Questions & Next Steps
- Final replace payload format & signing flow from the perps SDK/API.
- Exact spot API compatibility differences between the current main SDK and the perps SDK line.
- Dev-server endpoint, auth setup, and environment configuration for perps-era connector testing.
- Handling partial replacements (e.g. when price changes but size stays constant).
- Whether to expose replace capability to other strategies once stable.

Document owners: Ultrade MM team. Update as API details and strategy prototypes evolve.
