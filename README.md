# AIP Server (Reference Implementation)

The AIP Server is the neutral, protocol-only runtime for the Agentic Intent Protocol (AIP). It exposes the canonical HTTP, transport, validation, and ledger execution paths used by platforms, brand agents, and neutral operators. All behavior mirrors the normative specification in the companion [`aip-spec`](../aip-spec) repository.

## Relationship to `aip-spec`
- `aip-spec` defines canonical schemas, conformance tests, and transport rules.
- This repo turns that specification into a runnable FastAPI service.
- Every spec change should be reflected here via schema syncs and runtime updates.

---

## 1. Installation & Setup

### Clone the repository
```bash
git clone https://github.com/GouniManikumar12/aip-server-python.git
cd aip-server
```

### Prerequisites
- Python 3.11 (works on 3.10+, tested on 3.11)
- pip 23+
- Optional: Docker + Docker Compose for container workflows

### Install dependencies
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 2. Configuration

### Environment variables & credentials
| Variable | Purpose |
|----------|---------|
| `AIP_CONFIG_PATH` | Override path to `server.yaml` (defaults to `app/config/server.yaml`). |
| `AIP_BIDDERS_PATH` | Override path to `bidders.yaml`. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Service-account JSON for Google Pub/Sub or Firestore. |

Optional secrets (Postgres DSNs, Redis URLs, etc.) can live inside `server.yaml` under `ledger.options` or be injected as environment variables referenced from the YAML.

### Bidder configuration (`app/config/bidders.yaml`)
```yaml
bidders:
  - name: sample-bidder
    endpoint: https://example-bidder.invalid/bid
    public_key: "-----BEGIN PUBLIC KEY-----..."
    timeout_ms: 120
    pools:
      - default
      - retail
```
- `pools` enumerate the category pools the brand agent subscribes to.
- `public_key` is the PEM-encoded Ed25519 key used to verify `/aip/bid-response` signatures.

### Server configuration (`app/config/server.yaml`)
```yaml
listen:
  host: 0.0.0.0
  port: 8080
transport:
  nonce_ttl_seconds: 60
  max_clock_skew_ms: 500
ledger:
  backend: postgres  # or redis, firestore, in_memory
  options:
    dsn: postgresql://user:pass@localhost:5432/aip
auction:
  window_ms: 50
  distribution:
    backend: pubsub
    pubsub:
      project_id: your-gcp-project
      topic_prefix: aip-context
```

Environment-specific guidance:
- **Development**: use `backend: in_memory`, `distribution.backend: local`, and sample bidders.
- **Staging/Production**: point `ledger.options` to managed stores (Postgres/Firestore/Redis), lock down `listen.host`, use HTTPS termination, and rotate credentials regularly.

---

## 3. Supported Technologies
- **Python**: 3.10+
- **FastAPI**: async HTTP framework for `/context`, `/aip/bid-response`, `/events/{type}`, and admin routes
- **Storage backends**: In-Memory (dev/test), Redis, PostgreSQL, Google Cloud Firestore
- **Transport & security primitives**:
  - Publish/Subscribe fanout (`app/auction/fanout.py`) with local logging or Google Pub/Sub (pluggable for AWS SNS/SQS, Azure Event Grid, Kafka)
  - Ed25519 signatures (`app/transport/signatures.py`)
  - Canonical JSON serialization (`app/transport/canonical_json.py`)
  - Timestamp skew enforcement (`app/transport/timestamps.py`)
  - Nonce replay protection (`app/transport/nonces.py`)

---

## 4. Database Setup

### Firestore
1. Create a Firestore database in the desired GCP project.
2. Download a service-account JSON with Firestore + Pub/Sub (if needed) permissions.
3. Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`.
4. Configure:
   ```yaml
   ledger:
     backend: firestore
     options:
       project_id: your-gcp-project
       credentials_path: /path/to/key.json  # optional when env var is set
   ```

### PostgreSQL
1. Provision a database/user with privileges to create tables.
2. Set `ledger.backend: postgres` and provide either a DSN or discrete connection options under `ledger.options`.
3. The backend auto-creates `ledger_records` with a JSONB payload. Run migrations beforehand if you need indexes/partitions.

### Redis
1. Deploy Redis (standalone, cluster, or managed service).
2. Configure `ledger.backend: redis` with `options.url: redis://host:port/0`. Use `rediss://` for TLS endpoints.
3. Recommended for low-latency ledgers, nonce caches, and anti-replay enforcement.

### In-Memory
- Set `ledger.backend: in_memory` for local development or CI.
- Data is ephemeral; never use this backend in production.

---

## 5. Quick Start Guide

1. **Install dependencies** (see Installation & Setup).
2. **Configure bidders/server** (`app/config/*.yaml`).
3. **Run the API**:
   ```bash
   uvicorn app.main:app --reload --port 8080
   ```
4. **Docker / Compose**:
   ```bash
   docker-compose up --build
   # or
   docker build -t aip-server .
   docker run -p 8080:8080 aip-server
   ```
5. **Sanity checks**:
   ```bash
   python -m compileall app          # quick syntax check
   # Add pytest / mypy commands as suites are introduced
   ```
6. **Verify endpoints**:
   ```bash
   # Health
   curl http://localhost:8080/health

   # Submit a platform request (expect no_bid when no bidders respond)
   curl -X POST http://localhost:8080/aip/context \
     -H "Content-Type: application/json" \
     -d '{
           "request_id": "ctx_123",
           "session_id": "sess_001",
           "platform_id": "openai_chat",
           "query_text": "best CRM for small teams",
           "locale": "en-US",
           "geo": "US",
           "timestamp": "2025-11-14T18:22:00Z",
           "auth": {"nonce": "nonce_123", "sig": "sig_hmac"}
         }'

   # (During the auction window) send a mock bid response
   curl -X POST http://localhost:8080/aip/bid-response \
     -H "Content-Type: application/json" \
     -d '{
           "auction_id": "ctx_123",
           "bidder": "sample-bidder",
           "price": 1.23,
           "timestamp": "2025-01-01T00:00:00Z",
           "nonce": "abc123",
           "signature": "..."
         }'
   ```

---

## Bidder Registration Flow
1. Operators list bidder endpoints in `app/config/bidders.yaml` with public signing keys, timeouts, and category pools.
2. Each bidder listens to the publish/subscribe channels for its pools.
3. During auctions, bidders POST signed payloads to `/aip/bid-response` before the configured window closes.

---

## Asynchronous Auction Model

The AIP bidding model uses a **time-bounded asynchronous auction window** rather than full broadcast fanout. When a platform sends a `context_request`, the AIP Server classifies the request into one or more **category pools**. 

Only brand agents and advertiser networks that have explicitly subscribed to those pools receive the request. 

Distribution to bidders is handled through a cloud-agnostic **publish/subscribe transport**, starting with Google Pub/Sub in v1.0 and extendable to AWS SNS/SQS, Azure Event Grid, Kafka, or other message buses. 

After publishing the context, the AIP Server opens a short **auction window** (typically 30–70 ms) during which bidders may submit signed bids via `POST /aip/bid-response`. 

When the window closes, the server collects all bids received within the allowed timeframe, applies the AIP selection rules (CPA > CPC > CPX), and returns the `auction_result` to the platform. 

If no bids are received before the window expires, the server returns a valid `no_bid` response. This design enables scalable, category-aware bidding, minimizes latency, prevents unnecessary bidder fanout, and ensures that only relevant brand agents compete for each user intent.

## Request Flow: Files & Endpoints
1. **`POST /context` → `app/main.py`** – Platforms submit context; FastAPI validates against `aip-spec` schemas and forwards to the auction runner.
2. **Classification & publish → `app/auction/runner.py` + `app/auction/fanout.py`** – The runner selects subscribed bidders from `app/bidders/registry.py`, registers the auction with `BidResponseInbox`, and publishes `{auction_id, pools, context_request}` via the configured transport.
3. **Bidder responses → `POST /aip/bid-response`** – Brand agents send Ed25519-signed payloads. `BidResponseService` (in `app/events/handler.py`) enforces nonce freshness, timestamp skew, and signature validity before queuing bids.
4. **Window close & selection → `app/auction/runner.py` / `app/auction/selection.py`** – After `auction.window_ms`, the runner drains collected bids, applies CPA>CPC>CPX ordering, and persists results via `app/ledger/apply.py`.
5. **Response to platform** – `/context` returns the canonical `auction_result` (winner + creative + `serve_token`) or `{..., "no_bid": true}` when no bids arrive in time.
6. **Event callbacks → `POST /events/{event_type}`** – Platforms/agents log CPX/CPC/CPA events. `EventService` validates payloads and advances the ledger state machine.

---

## Roadmap to v1.1
- Full coverage of `aip-spec/tests` conformance suite in CI.
- Configurable storage engines (in-memory, Redis, Postgres, Firestore) with parity semantics.
- Ledger FSM hardening plus deterministic replay protections.
- Transport hardening (nonce rotation policies, signature caching, canonical JSON round-trips).
- Reference load/seed scripts kept in sync with spec fixtures.
