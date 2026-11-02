"""Game constants. The only place where the rules change - see docs/backend_roadmap.md."""

ROOM_CODE_LENGTH = 6      # wireframes show 5, RoomCode in the ERD says 6 -> 6, the constant is one line
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # without I, O, 0, 1 - so the code can be copied from speech
ROUNDS_RANGE = (3, 10)    # range from the wireframe, default 5 according to Sequential.drawio
MAX_PLAYERS = 10          # Connected players (3 / 10) from the wireframe
ROUND_SECONDS = 30        # the loop in Sequential.drawio
REVEAL_SECONDS = 8        # the mock writes "Next round in 5…", we keep 8 s to read the results
PRICE_BAND = (500, 20_000)   # CZK/night - the lower bound cuts trips, the upper castles for 1.1 mil.
