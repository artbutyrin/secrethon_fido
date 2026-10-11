"""Server entry point. Run from the repo root:

    python3 main.py                  (or the green Run button in PyCharm)
    uvicorn main:app --reload        (restarts on code changes)

Then open http://127.0.0.1:8000/docs. The API itself is in backend/app/api.py.
"""
import uvicorn

from backend.app.api import app  # noqa: F401  (uvicorn main:app finds it here)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
