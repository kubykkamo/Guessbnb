import math

def points(guess:int, real: float) -> int:
    return round(100 * math.exp(-2.3 * abs(guess - real) / real))


def error_pct(guess: int, real: float) -> float:
    return abs(guess - real) / real * 100


