#app entry point

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from src.repositories import listing_repository
from src.repositories.db import connect



@asynccontextmanager
async def lifespan(app: FastAPI):
    
    app.state.conn = await connect() #db connection
   
    app.state.rooms = {}
    try:
        yield
    finally:
        await app.state.conn.close()


app = FastAPI(title="Guessbnb API", lifespan=lifespan)

from src.api import ws
app.include_router(ws.router)


# F0 ------ endpoints ------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """life check"""
    return {"status": "ok"}


@app.get("/api/cities")
async def get_cities(request: Request) -> dict[str, list[str]]:
    """Cities list that will be used for host choice of playing"""
    cities = await listing_repository.list_cities(request.app.state.conn)
    return {"cities": cities}

# F2 ----
