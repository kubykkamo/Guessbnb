"""Entry point FastAPI aplikace.

SPUŠTĚNÍ: uvicorn src.api.main:app --workers 1

`--workers 1` je tvrdý strop, ne volba. Registry místností (`app.state.rooms`) žijí v RAM
tohoto procesu — víc workerů znamená víc kopií registry a hru rozštípnutou mezi procesy.
Viz docs/backend_roadmap.md, riziko 1.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.repositories import listing_repository
from src.repositories.db import connect


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Spojení do DB i registry her patří ke životu procesu, ne k requestu."""
    app.state.conn = await connect()
    # Room registries: zatím prázdné. Plní je F2 (transport), dohled nad vyprázdněnými
    # místnostemi přebírá RoomSupervisor ve F4 — docs/backend_roadmap.md #L166, #L211.
    app.state.rooms = {}
    try:
        yield
    finally:
        await app.state.conn.close()


app = FastAPI(title="Guessbnb API", lifespan=lifespan)


# F0 ------ endpoints ------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Živostní sonda. Záměrně nesahá do DB, ať je green co nejdřív po startu."""
    return {"status": "ok"}


@app.get("/api/cities")
async def get_cities(request: Request) -> dict[str, list[str]]:
    """Města, z nichž si hostitel vybírá hru — jen ta, kam jsme dovezli ETL."""
    cities = await listing_repository.list_cities(request.app.state.conn)
    return {"cities": cities}
