"""Konstanty hry. Jediné místo, kde se mění pravidla — viz docs/backend_roadmap.md."""

ROOM_CODE_LENGTH = 6      # wireframy ukazují 5, RoomCode v ERD říká 6 → 6, konstanta je jeden řádek
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # bez I, O, 0, 1 – ať se kód dá opsat ze slova
ROUNDS_RANGE = (3, 10)    # rozsah z wireframu, default 5 podle Sequential.drawio
MAX_PLAYERS = 10          # Connected players (3 / 10) z wireframu
ROUND_SECONDS = 30        # smyčka v Sequential.drawio
REVEAL_SECONDS = 8        # mock píše "Next round in 5…", necháváme 8 s na přečtení výsledků
PRICE_BAND = (500, 20_000)   # CZK/noc – spodní mez stříhá výlety, horní hrady za 1,1 mil.
