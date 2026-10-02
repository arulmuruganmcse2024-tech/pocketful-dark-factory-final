# Pocketful Stage 2

Build:
docker build -t pocketful-stage-2 .

Run:
docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-2

Run without Docker (Python 3.11+), from this folder:
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}

The service listens on 0.0.0.0 and honors PORT. It has no runtime network dependency.
This folder serves stage 2 by default (stage.py); POCKETFUL_STAGE overrides it.
State is stored in SQLite at POCKETFUL_DB (default /tmp/pocketful/state.db).
