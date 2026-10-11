"""Step 6: the HTTP API on SQLite. Opens on http://127.0.0.1:8000 (interactive docs at /docs).

Run:  python step6_serve.py
Try:  curl -X POST localhost:8000/runs -H 'content-type: application/json' \
           -d '{"disease": "Alzheimer disease", "target": "BACE1 inhibitor"}'
      curl localhost:8000/runs/<run_id>
The database is backend/data/unobio.db (set UNOBIO_DB to use another file).
"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.app.api:app", host="127.0.0.1", port=8000, reload=False)
