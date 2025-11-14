# AIP Server (Reference Implementation)

The AIP Server is the neutral, protocol-only runtime for the Agentic Intent Protocol (AIP). It provides the canonical HTTP, transport, validation, and ledger execution paths that every bidder integration can rely on. All behavior is derived directly from the normative definitions in the companion [`aip-spec`](../aip-spec) repository.

## Relationship to `aip-spec`
- `aip-spec` defines canonical schemas, conformance tests, and transport rules.
- This `aip-server` repository turns those rules into a runnable FastAPI service.
- Any change in the spec should be reflected here via schema sync + updated runtime logic.

## Local Development
```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Environment variables and YAML configs inside `app/config/` control bidder fanout, ledger storage backends, and transport settings.

## Bidder Registration Flow
1. Operators list bidder endpoints in `app/config/bidders.yaml` with public signing keys and timeouts.
2. Each bidder declares the category pools it subscribes to so the server can route `context_request` messages selectively.
3. Bidders implement the AIP schema contracts from `aip-spec` and interact via the neutral HTTP surface.

## Asynchronous Auction Model

The AIP bidding model uses a **time-bounded asynchronous auction window** rather than full broadcast fanout. When a platform sends a `context_request`, the AIP Server classifies the request into one or more **category pools**. Only brand agents and advertiser networks that have explicitly subscribed to those pools receive the request. Distribution to bidders is handled through a cloud-agnostic **publish/subscribe transport**, starting with Google Pub/Sub in v1.0 and extendable to AWS SNS/SQS, Azure Event Grid, Kafka, or other message buses. After publishing the context, the AIP Server opens a short **auction window** (typically 30–70 ms) during which bidders may submit signed bids via `POST /aip/bid-response`. When the window closes, the server collects all bids received within the allowed timeframe, applies the AIP selection rules (CPA > CPC > CPX), and returns the `auction_result` to the platform. If no bids are received before the window expires, the server returns a valid `no_bid` response. This design enables scalable, category-aware bidding, minimizes latency, prevents unnecessary bidder fanout, and ensures that only relevant brand agents compete for each user intent.

## Roadmap to v1.1
- Full coverage of `aip-spec/tests` conformance suite in CI.
- Configurable storage engines (in-memory, Redis, Postgres) with parity semantics.
- Ledger FSM hardening plus deterministic replay protections.
- Transport hardening (nonce rotation policies, signature caching, canonical JSON round-trips).
- Reference load/seed scripts kept in sync with spec fixtures.
