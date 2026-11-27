from fastapi import APIRouter, WebSocket, WebSocketDisconnect
router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_text()
            await ws.send_text(f"Server received: {msg}")
    except WebSocketDisconnect:
        pass

