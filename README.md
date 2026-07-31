# Inventorius API

![Code coverage badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fcomputemachines%2Fc6358499cfa820bcffe8535e6cabd586%2Fraw%2Fcoverage-inventory-v2-api-badge.json)
![Build](https://github.com/computemachines/inventorius-api/actions/workflows/build-push.yml/badge.svg)

Flask REST API backend for the Inventorius inventory management system. Provides endpoints for SKU management, batch tracking, search, and the unified trigger schema system.

## Quick Start (Development)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Set up virtual environment and install dependencies
uv venv .venv
uv pip install -r requirements.txt
uv pip install -e .

# Start MongoDB (macOS)
brew services start mongodb-community

# Run development server
FLASK_DEBUG=1 uv run flask --app inventorius run --port 8000
```

The API will be available at http://localhost:8000

## Project Structure

```
src/inventorius/
├── __init__.py          # Flask app factory
├── routes.py            # Core REST endpoints (SKU, Batch, Bin)
├── data_models.py       # MongoDB document models
├── schema/              # Unified trigger schema system
│   ├── trigger_engine.py    # Schema evaluation engine
│   ├── catalog.py           # Built-in schema installation policy
│   ├── routes.py            # /api/schema/* endpoints
│   └── sample_schemas.py    # SKU and Batch schema definitions
└── util.py              # ID generation, helpers

tests/
├── test_inventorius.py  # Integration tests
├── test_data_models.py  # Model tests
└── test_schema.py       # Schema system tests
```

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/sku/<id>` | Get SKU by ID |
| `POST /api/sku` | Create new SKU |
| `GET /api/batch/<id>` | Get Batch by ID |
| `POST /api/batch` | Create new Batch |
| `GET /api/search?q=` | Full-text search |
| `POST /api/schema/<name>/evaluate` | Evaluate schema for dynamic forms |

## Schema System

The unified trigger schema system enables dynamic form generation. See the [documentation](https://github.com/computemachines/inventorius-docs) for details.

```bash
# List available schemas
curl http://localhost:8000/api/schema/list

# Install missing SKU and Batch schemas without replacing edits
uv run flask --app inventorius schema bootstrap

# Evaluate SKU schema with Resistor selected
curl -X POST http://localhost:8000/api/schema/sku/evaluate \
  -H "Content-Type: application/json" \
  -d '{"active_mixins": ["ItemTypeSelector"], "field_values": {"item_type": "Resistor"}}'
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Deliberate state-machine soak run (10,000 examples instead of 100)
HYPOTHESIS_SLOW=true uv run pytest tests/test_inventorius.py::TestInventorius

# Run with coverage
uv run coverage run --source=inventorius -m pytest
uv run coverage report
```

## Container Release Channels

Pushes to `development` publish both the moving `development` image and an
immutable full-revision image. Pushes to `main` publish only the immutable image:

```bash
docker pull ghcr.io/computemachines/inventorius-api:sha-<full-40-character-commit>
```

The `main` branch is the component promotion source for coordinated workspace
releases; it does not publish a mutable deployment tag. Staging advances from a
coordinated release-candidate manifest, and production uses the accepted image
digest from that manifest. `latest` is not a deployment channel. See
[inventorius-deploy](https://github.com/computemachines/inventorius-deploy) for
the full Docker Compose stack and the workspace `RELEASING.md` for promotion and
acceptance policy.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_HOST` | `localhost` | MongoDB hostname |
| `MONGO_PORT` | `27017` | MongoDB port |
| `FLASK_DEBUG` | `0` | Enable debug mode (auto-reload) |
| `BUILD_ID` | `dev` | Immutable full source revision baked into the image |
| `INVENTORIUS_ENVIRONMENT` | `unassigned` | Runtime deployment environment, also used by Sentry |
| `INVENTORIUS_RELEASE_MANIFEST_PATH` | unset | Optional schema-1 release manifest; its API revision must exactly match `BUILD_ID` before its product release is exposed |
| `SENTRY_DSN` | unset | Enables error reporting with release `inventorius-api@BUILD_ID`; no PII or traces are sent |

When GitHub repository configuration provides `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`,
and `SENTRY_API_PROJECT`, non-PR image builds create or update the matching
Sentry release. Deployment environments are recorded separately only after
runtime convergence.

`GET /api/status` reads the optional manifest at request time. It exposes its
`product_release` only when the manifest is schema 1 and its `components.api`
revision exactly equals the immutable `BUILD_ID`; missing, malformed, and stale
manifests fail closed to the environment name. The response contains no
credentials, sessions, or inventory data. Sentry keeps the immutable component
release and dynamically tags each request with the same resolved product release.

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created (resource returned) |
| 204 | No Content (success, no body) |
| 400 | Bad Request (client error) |
| 404 | Not Found |
| 409 | Conflict (duplicate ID, etc.) |
| 500 | Internal Server Error |
