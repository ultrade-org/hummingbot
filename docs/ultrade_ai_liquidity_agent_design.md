# Ultrade Liquidity Agent – Design Outline

## 1. Problem Statement
Token listers want persistent, healthy order book depth during listings without micro-managing strategy parameters. Current manual PMM configurations adapt slowly to market regime changes and expose gaps during updates. We propose an automated “Liquidity Agent” that monitors real-time performance metrics, compares them to configurable goals, and adjusts Ultrade-specific PMM parameters (including forthcoming bulk-replace workflows) to keep liquidity targets within bounds.

## 2. High-Level Goals
- Maintain desired spread, depth tiers, and inventory utilisation while limiting exposure/risk.
- React to market changes (volatility spikes, inventory imbalance, demand shocks) within seconds.
- Provide goal-driven configuration profiles per token, adjustable by the lister (web portal / config files).
- Deliver auditable decisions, safety limits, and the ability to pause/override.
- Work alongside the upcoming Ultrade PMM (uPMM) bulk replace functionality to modify quotes with minimal downtime.
- Treat bulk replace as dependent on the upcoming perps SDK/API line; current spot work should preserve single and bulk create/cancel behavior until that migration is complete.

## 3. System Overview

```
               +------------------+       +-------------------+
Market Data -->| Telemetry Engine |-----> | Metrics Store /   |---+
(Ultrade WS/   +------------------+       | Feature Extractor |   |
 REST/API)           |                      +-------------------+   |
                    |                          (Prometheus/DB)      |
                    v                                             v v
            +----------------+                +-----------------------+
            | Strategy State |<-------------->| Decision Engine       |
            | (PMM/uPMM)     |  adjustments   | (Rules/ML Controller) |
            +----------------+                +-----------------------+
                    |                                   |
                    v                                   v
               +-------------------------------+    +---------------+
               | Ultrade Connector w/ Replace  |    | Audit Logger  |
               | (create/cancel/replace APIs)  |    +---------------+
               +-------------------------------+
```

### Components
1. **Telemetry Engine**
   - Collects strategy events (orders created/replaced, fills, cancellations), Ultrade order book snapshots, trade tape, and internal inventory/PNL metrics.
   - Publishes structured events (e.g., via asyncio queues) to both the metrics store and decision engine.

2. **Metrics Store & Feature Extractor**
   - Time-series database (Prometheus/Influx/Postgres) storing KPIs: live spread coverage, depth per tier, order uptime %, cancel rates, realised spread, inventory delta, PnL.
   - Feature extractor generates derived indicators for the decision engine (rolling volatility, fill ratio, latency, slippage).

3. **Decision Engine**
   - Reads goal profile for each token (min depth, max spread, turnover targets, inventory constraints).
   - Produces parameter adjustments and order actions.
   - Implementation phases:
     - Phase A: rule-based heuristics + PID controllers to nudge spreads/order levels / tolerance.
     - Phase B: contextual bandit or gradient-boosted policy mapping features to optimal parameter sets.
     - Phase C: reinforcement learning or MPC with predictive simulation.
   - Provides safety checks before applying decisions (bounded adjustments, cooldowns).

4. **Strategy Orchestrator**
   - Interface around PMM/uPMM to apply adjustments without restarts:
     - Update runtime parameters (`order_refresh_tolerance_pct`, `filled_order_delay`, `inventory_skew`, etc.).
     - Enqueue explicit order modifications (via bulk replace once available).
     - Maintain fallbacks: revert to last known-good config on errors.

5. **Ultrade Connector Enhancements**
   - Capability flags: `supports_bulk_replace`.
   - New methods: `bulk_replace_orders`, success/error telemetry.
   - Circuit breaker toggles to fall back to cancel/create after repeated failures.

6. **Audit & Control Plane**
   - Log every decision (inputs, suggested action, result, ΔKPIs).
   - Provide operator controls: set goals, override parameters, pause/resume agent.
   - Optionally expose webhook or UI (dashboard) for token listers.

## 4. Goal & Policy Configuration
- Each token has a profile (YAML/JSON) specifying:
  - Target spread ranges per depth tier (e.g., 0.5% @ 5k units, 1% @ 20k units).
  - Minimum live orders per side.
  - Inventory bounds (base/quote).
  - Acceptable cancel/create cadence and API budget.
  - Profitability or cost metrics (e.g., spread capture).
- Profiles also define priority weights; e.g., maintain depth > limit risk > maximise profit.
- Provide default templates (conservative, balanced, aggressive) reusable by new listings.

## 5. Detailed Workflow
1. **Bootstrap**
   - Load goal profile.
   - Start telemetry subscriptions.
   - Initialise PMM/uPMM with baseline configuration.

2. **Continuous Loop (every N seconds)**
   ```
   gather_metrics()
   compute_current_state()
   for each goal:
       evaluate deviation
   candidate_actions = policy(state, goals, history)
   candidate_actions = enforce_safety(candidate_actions)
   apply_actions(candidate_actions)
   log_decision(state, actions, results)
   update_learning_buffers()
   ```

   - `apply_actions` may update parameters or issue `bulk_replace` command batches.
   - Safety ensures cooldowns, max exposure, and API rate limits.

3. **Learning / Adaptation**
   - Store (state, action, reward) tuples to training buffer.
   - Schedule offline training jobs (nightly) to refine policy models.
   - Deploy new models behind feature flags with shadow mode comparisons.

## 6. Phased Implementation Roadmap

### Phase -1 – Connector Platform Upgrade
- Upgrade this Hummingbot branch to the latest target Hummingbot version.
- Re-verify spot single order and bulk create/cancel behavior after the upgrade.
- Move the connector from the current main Ultrade SDK to the upcoming perps SDK line.
- Adapt spot trading support to any SDK/API changes introduced by the perps platform.
- Use the Ultrade dev4 server (`https://api.dev4.ultradedev.net/`) for perps SDK and bulk-replace testing until those APIs are available on live testnet.
- Add an explicit connector order-management mode selector: `single`, `bulk`, or `bulk_replace`.

### Phase 0 – Foundations
- Instrument PMM/uPMM with telemetry hooks.
- Implement metrics collection + dashboards (Grafana or equivalent).
- Define goal schema and static configuration templates.

### Phase 1 – Reactive Rule Engine
- Build controller service adjusting parameters via Hummingbot internal APIs.
- Implement heuristics (e.g., widen spread when volatility > threshold, increase order levels when depth < target).
- Integrate safety guardrails and audit logging.

### Phase 2 – Model-Driven Controller
- Collect historical data, train supervised/contextual models.
- Introduce policy selection (choose from prevalidated parameter sets).
- Add dynamic weighting of conflicting goals based on priority.

### Phase 3 – Predictive / RL Agent
- Build simulation environment using recorded market data + Ultrade API sandbox.
- Train RL or MPC for multi-step decision-making.
- Validate via shadow mode against live strategy before enabling.

### Phase 4 – Ecosystem Tools
- Web dashboard for token listers: configure goals, watch KPIs, view agent decisions.
- Alerting (Slack, email) on goal deviations or safety triggers.
- Support multiple markets/pairs concurrently with resource allocation logic.

## 7. Data & Infrastructure Needs
- Low-latency access to Ultrade market data (existing WS/REST).
- Persistent storage for metrics (Prometheus/Influx/Postgres).
- Optional message bus (Kafka/Redis) if decoupling agent from Hummingbot core.
- Compute budget for training and inference (on-node lightweight models, off-node heavy training).
- Secure credential management for agents operating on behalf of listers.

## 8. Safety & Compliance
- Hard-coded bounds on spreads, order sizes, inventory usage.
- Circuit breakers (disable agent on repeated failures, high error rates, or connectivity loss).
- Manual override/pause accessible via CLI or dashboard.
- Comprehensive audit trail (timestamp, state snapshot, decision, outcomes).
- Optional KYC/AML checks depending on jurisdictional requirements.

## 9. Open Questions
- Final Ultrade bulk replace response semantics and signing workflow in the perps SDK.
- Spot compatibility differences between the current SDK and the perps SDK/dev4 API.
- Dev4 private auth details for connector smoke tests and perps-era regression tests.
- How to best estimate “liquidity value” or rewards for RL training (PnL vs synthetic metrics).
- Whether to centralise agent logic (cloud service) or keep per-node to minimise latency and security risk.
- Approach for multi-agent coordination if several tokens share capital.

## 10. Next Steps
1. Upgrade the Hummingbot base and verify existing Ultrade spot behavior still works.
2. Migrate the connector to the perps SDK line and point testing at the Ultrade dev server.
3. Restore or adapt spot bulk create/cancel support on the perps SDK.
4. Implement the `single` / `bulk` / `bulk_replace` order-management selector.
5. Add bulk replace support and then resume Phase 0 liquidity-agent instrumentation.

This document summarises the concept and high-level architecture to enable future sessions to estimate effort, plan sprints, and begin implementation.
