# deploy-test-flask

Minimal Python Flask application for testing Git deployments.

## Routes

- `/` — HTML home page
- `/health` — JSON health check

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PORT=8000 gunicorn --bind 0.0.0.0:$PORT app:app
```

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```
