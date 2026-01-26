# Inventorius API

![Code coverage badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fcomputemachines%2Fc6358499cfa820bcffe8535e6cabd586%2Fraw%2Fcoverage-inventory-v2-api-badge.json)

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

# Evaluate SKU schema with Resistor selected
curl -X POST http://localhost:8000/api/schema/sku/evaluate \
  -H "Content-Type: application/json" \
  -d '{"active_mixins": ["ItemTypeSelector"], "field_values": {"item_type": "Resistor"}}'
```

## Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run coverage run --source=inventorius -m pytest
uv run coverage report
```

## Docker Deployment

The API is deployed as a Docker container via GitHub Actions CI/CD:

```bash
docker pull ghcr.io/computemachines/inventorius-api:latest
```

See [inventorius-deploy](https://github.com/computemachines/inventorius-deploy) for the full Docker Compose stack.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_HOST` | `localhost` | MongoDB hostname |
| `MONGO_PORT` | `27017` | MongoDB port |
| `FLASK_DEBUG` | `0` | Enable debug mode (auto-reload) |

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
