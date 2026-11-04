"""State machine of one room - the only place that touches game state. See F1 in docs/backend_roadmap.md."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from src.config import REVEAL_SECONDS, ROUND_SECONDS
from src.game.scoring import error_pct, points
from src.models import Listing


class Phase(Enum):
    LOBBY = "LOBBY"
    STARTING = "STARTING"
    ROUND_OPEN = "ROUND_OPEN"
    REVEALING = "REVEALING"
    FINISHING = "FINISHING"
    GAME_OVER = "GAME_OVER"


class Clock(Protocol):
    def now(self) -> int:
        """Epoch milliseconds."""

@dataclass
class Listing:
    id: int
    city: str
    price: int

@dataclass
class Player:
    player_id: str
    display_name: str
    is_host: bool = False
    connected: bool = True
    score: int = 0
# --- COMMANDS (in-process; wire models arrive in F2/protocol.py) ---

@dataclass(frozen=True)
class SetSettings:
    player_id: str
    city: str
    rounds: int

@dataclass(frozen=True)
class StartGame:
    player_id: str
    listings: list[Listing]      # drawn up-front by the caller (#L156) - never by handle()

@dataclass(frozen=True)
class SubmitGuess:
    player_id: str
    round: int                   # must equal room.round_token
    price: int

@dataclass(frozen=True)
class NextRound:
    player_id: str

@dataclass(frozen=True)
class DeadlineReached:           # minted by the actor loop, never by a client
    token: int


# --- EVENTS ---

@dataclass
class LobbyUpdated:
    players: list[Player]
    settings: dict

@dataclass
class GameStarted:
    rounds_total: int
    city: str

@dataclass
class RoundStarted:
    round_no: int
    rounds_total: int
    round: int                   # the token, travels back on every guess
    listing: Listing
    photos: list
    deadline_ms: int

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
class GameFinished:
    standings: list[dict]
    persisted: bool = False

@dataclass
class Error:
    code: str
    message: str


@dataclass
class Room:
    room_code: str
    clock: Clock
    players: dict[str, Player] = field(default_factory=dict)
    phase: Phase = Phase.LOBBY
    city: str | None = None
    rounds_total: int = 5        # default per Sequential.drawio, range ROUNDS_RANGE
    round_no: int = 0
    round_token: int = 0
    deadline_ms: int | None = None
    listing: Listing | None = None
    guesses: dict[str, int] = field(default_factory=dict)
    draw: list[Listing] = field(default_factory=list)

    async def handle(self, cmd) -> list:
        """Command -> events. Never touches the DB, the socket or a real clock."""
        match cmd:
            case SetSettings(player_id=pid, city=city, rounds=rounds):
                if err := self._require_host(pid, Phase.LOBBY):
                    return [err]
                return self._set_settings(city, rounds)

            case StartGame(player_id=pid, listings=listings):
                if err := self._require_host(pid, Phase.LOBBY):
                    return [err]
                return self._start_game(listings)

            case SubmitGuess(player_id=pid, round=token, price=price):
                if err := self._require_player(pid, Phase.ROUND_OPEN):
                    return [err]
                return self._submit_guess(pid, token, price)

            case NextRound(player_id=pid):
                if err := self._require_host(pid, Phase.REVEALING):
                    return [err]
                return self._advance()

            case DeadlineReached(token=token):
                if token != self.round_token:
                    return []          # stale timer - discard, do not error a client
                return self._deadline()

            case _:
                return [Error("UNKNOWN_COMMAND", type(cmd).__name__)]

    # --- guards ---

    def _require_player(self, player_id: str, phase: Phase) -> Error | None:
        if player_id not in self.players:
            return Error("NOT_SEATED", f"{player_id} is not in this room")
        if self.phase is not phase:
            return Error("INVALID_STATE", f"{self.phase.value}: needs {phase.value}")

    def _require_host(self, player_id: str, phase: Phase) -> Error | None:
        if err := self._require_player(player_id, phase):
            return err
        if not self.players[player_id].is_host:
            return Error("NOT_HOST", "only the host may do that")

    # --- transitions ---

    def _set_settings(self, city: str, rounds: int) -> list:
        self.city, self.rounds_total = city, rounds
        return [LobbyUpdated(self._roster(), {"city": city, "rounds": rounds})]

    def _start_game(self, listings: list[Listing]) -> list:
        self.phase = Phase.STARTING        # #L82, crossed within this one call
        self.draw = list(listings)
        self.round_no = 0
        return [GameStarted(self.rounds_total, self.city), *self._open_round()]

    def _open_round(self) -> list:
        self.round_no += 1
        self.round_token += 1              # a counter, so tests can send an old one
        self.listing = self.draw[self.round_no - 1]
        self.guesses = {}
        self.phase = Phase.ROUND_OPEN
        self.deadline_ms = self.clock.now() + ROUND_SECONDS * 1000
        return [RoundStarted(self.round_no, self.rounds_total, self.round_token,
                             self.listing, [], self.deadline_ms)]

    def _submit_guess(self, player_id: str, token: int, price: int) -> list:
        if token != self.round_token:
            return [Error("STALE_ROUND", f"guess carries round {token}")
                    ] if True else []      # state untouched - see the STALE_ROUND acceptance
        self.guesses[player_id] = price
        waiting = self._waiting()
        events: list = [GuessAck(self.round_no), GuessCount(len(self.guesses), len(waiting) + len(self.guesses))]
        if not waiting:
            events += self._evaluate()     # everyone in - do not idle until the timer
        return events

    def _deadline(self) -> list:
        if self.phase is Phase.ROUND_OPEN:
            return self._evaluate()
        if self.phase is Phase.REVEALING:
            return self._advance()
        return []

    def _evaluate(self) -> list:
        if self.phase is not Phase.ROUND_OPEN:
            return []                      # <- round evaluated exactly once
        results = []
        for p in self.players.values():
            guess = self.guesses.get(p.player_id)
            got = points(guess, self.listing.price) if guess is not None else 0
            p.score += got
            results.append({"player_id": p.player_id, "display_name": p.display_name,
                            "guess": guess, "points": got,
                            "error_pct": error_pct(guess, self.listing.price) if guess is not None else None})
        self.phase = Phase.REVEALING
        self.deadline_ms = self.clock.now() + REVEAL_SECONDS * 1000
        return [RoundEnded(self.listing.price, results, self._standings())]

    def _advance(self) -> list:
        if self.round_no >= self.rounds_total:
            self.phase = Phase.FINISHING
            self.phase = Phase.GAME_OVER
            self.deadline_ms = None
            return [GameFinished(self._standings())]
        return self._open_round()

    # --- read-only helpers ---

    def _waiting(self) -> list[Player]:
        """Connected players who have not guessed yet - a disconnect must not freeze the round."""
        return [p for p in self.players.values() if p.connected and p.player_id not in self.guesses]

    def _roster(self) -> list[Player]:
        return list(self.players.values())

    def _standings(self) -> list[dict]:
        """Sorted by score; equal scores keep seat order (the roadmap does not pick a tiebreak)."""
        return [{"player_id": p.player_id, "display_name": p.display_name, "score": p.score}
                for p in sorted(self.players.values(), key=lambda p: -p.score)]
