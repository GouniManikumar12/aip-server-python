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
2. The registry module loads the YAML file on startup and exposes `/bid` fanout targets.
3. Bidders implement the AIP schema contracts from `aip-spec` and interact via the neutral HTTP surface.

## Roadmap to v1.1
- Full coverage of `aip-spec/tests` conformance suite in CI.
- Configurable storage engines (in-memory, Redis, Postgres) with parity semantics.
- Ledger FSM hardening plus deterministic replay protections.
- Transport hardening (nonce rotation policies, signature caching, canonical JSON round-trips).
- Reference load/seed scripts kept in sync with spec fixtures.
