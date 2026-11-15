"""AdaptED API. Stage 1 (database): only the health check. The API of epics E1–E8 comes in stage 2."""

from fastapi import FastAPI
from sqlalchemy import text

from app.db.session import engine

app = FastAPI(title="AdaptED API", version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict:
    with engine.connect() as conn:
        revision = conn.execute(text("SELECT current_user")).scalar_one()
    return {"status": "ok", "db_user": revision}
