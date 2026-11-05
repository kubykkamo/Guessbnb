import pytest
import aiosqlite
from src.game.state import Player, Room


class FakeClock():
    def __init__(self):
        self._current_time_ms: float = 0.0


    def now(self) -> int:
        return int(self._current_time_ms)

    def advance(self, seconds: float):
        self._current_time_ms += seconds * 1000

@pytest.fixture
def clock():
    return FakeClock()
        
@pytest.fixture
async def seed_listings():
    db = await aiosqlite.connect(":memory:")

    await db.execute("""
    CREATE TABLE LISTINGS (
    id TEXT PRIMARY KEY,
    city TEXT,
    price INTEGER
    );
    """
    )

    await db.execute("INSERT INTO listings VALUES ('1', 'Prague', '2500')")
    await db.execute("INSERT INTO listings VALUES ('2', 'Prague', '2300')")
    await db.commit()

    return db

@pytest.fixture
def room_with_two_players(clock):


    host = Player(player_id="p1", display_name="Pepa", is_host=True, connected=True, score=0)
    guest = Player(player_id="p2", display_name="Franta", is_host=False, connected=True, score=0)

    room = Room(room_code="TEST", clock=clock, players={"p1": host, "p2": guest})

    return room