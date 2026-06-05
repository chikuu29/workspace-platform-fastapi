
# Run all tests
uv run pytest tests/ -v

# Layer 1 only — fastest, run on every save
uv run pytest tests/unit/ -v

# Layer 2 only
uv run pytest tests/integration/ -v

# Layer 3 only
uv run pytest tests/api/ -v

# Run a specific service
uv run pytest tests/unit/services/test_sequence_service.py -v

# Run with coverage report
uv run pytest tests/ --cov=app --cov-report=term-missing

