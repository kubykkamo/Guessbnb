from enum import Enum
from dataclasses import dataclass

class Phase(Enum):
    LOBBY = "LOBBY"
    STARTING = "STARTING"
    ROUND_OPEN = "ROUND_OPEN"
    REVEALING = "REVEALING"
    ROUND_ENDED = "ROUND_ENDED"
    GAME_OVER = "GAME_OVER"

@dataclass
class Player():
    player_id: str
    display_name: str
    is_host: bool
    score: int = 0
    connected: bool = True

# --- COMMANDS (F1: internal, in-process. The wire models come in F2/protocol.py) ---

@dataclass(frozen=True)
class SetSettings:
    player_id: str
    city: str
    rounds: int

@dataclass(frozen=True)
class StartGame:
    player_id: str

@dataclass(frozen=True)
class SubmitGuess:
    player_id: str      # from the connection registry - the wire payload does NOT carry it
    round: int          # must equal room.round_token, else STALE_ROUND
    price: int

@dataclass(frozen=True)
class NextRound:
    player_id: str

@dataclass(frozen=True)
class DeadlineReached:      
    token: int

# --- EVENTS ---

@dataclass
class GuessAck:
    round_no: int

@dataclass
class GuessCount:
    n: int
    of: int

@dataclass
class RoundEnded:
    actual_price: float
    results: list[dict]
    standings: list[dict]

@dataclass
class Error:
    code: str
    message: str

@dataclass
class Room():
    room_code: str
    phase: Phase = Phase.LOBBY
    current_roud: int = 0


