import pytest

from src.game.scoring import points, error_pct


@pytest.mark.parametrize(
    "guess, real, expected",
    [
        (1000, 1000, 100),
        (1100, 1000, 79),
        (1300, 1000, 50),
        (700, 1000, 50),
        (2000, 1000, 10),
        (1, 1000, 10),
    ],
)
def test_points(guess, real, expected):
    assert points(guess, real) == expected


@pytest.mark.parametrize(
    "guess, real, expected",
    [
        (1000, 1000, 0.0),
        (1100, 1000, 10.0),
        (1300, 1000, 30.0),
        (700, 1000, 30.0),
        (2000, 1000, 100.0),
        (1, 1000, 99.9),
    ],
)
def test_error_pct(guess, real, expected):
    assert error_pct(guess, real) == pytest.approx(expected)


# --- the property test F1 asks for (#L184) ------------------------------------
# No hypothesis: requirements-dev.txt (#L164) names pytest, pytest-asyncio and
# websockets only, so the sweep is a fixed grid. A fixed grid is also what you want
# here - the failing pair comes back identically on the next run.
# `real` never goes below 1; CHECK (price > 0) in schema.py keeps the denominator
# away from zero, which the last test below pins down (P-012).

REALS = [500, 1000, 1700, 4999, 20_000]          # the PRICE_BAND edges (#L43) and some inside it
FACTORS = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1.0,
           1.01, 1.1, 1.5, 2.0, 3.2, 3.4, 5.0, 10.0, 40.0]


def guesses_for(real):
    """Guesses from a hundredth of the price to forty times it, never under 1 CZK."""
    return sorted({max(1, round(real * f)) for f in FACTORS})


def deviation(guess, real):
    return abs(guess - real) / real


def test_points_always_land_between_0_and_100():
    """#L184 - points are always in 0-100."""
    for real in REALS:
        for guess in guesses_for(real):
            got = points(guess, real)
            assert isinstance(got, int), f"points({guess}, {real}) returned {got!r}"
            assert 0 <= got <= 100, f"points({guess}, {real}) returned {got}"


def test_points_never_grow_as_deviation_grows():
    """#L184 - decrease as deviation increases. Non-increasing rather than strictly:
    round() makes neighbours equal, e.g. on real 1000 both 1000 and 1001 give 100.
    """
    for real in REALS:
        by_dev = sorted(guesses_for(real), key=lambda g: deviation(g, real))
        scores = [points(g, real) for g in by_dev]
        for closer, farther, nearer_score, farther_score in zip(
                by_dev, by_dev[1:], scores, scores[1:]):
            assert farther_score <= nearer_score, (
                f"real={real}: deviation grows {deviation(closer, real):.3f} -> "
                f"{deviation(farther, real):.3f} but points go "
                f"{nearer_score} -> {farther_score}")


def test_overvaluing_costs_the_same_as_undervaluing():
    """#L150 - symmetry is intentional, overvaluing by 30 % costs the same as
    undervaluing by 30 %. Only asked where the mirrored guess is still a price.
    """
    for real in REALS:
        for half_step in (100, 300, 700, 999):
            if real - half_step < 1:
                continue
            assert points(real + half_step, real) == points(real - half_step, real), \
                f"real={real}, +-{half_step}"


def test_a_guess_over_three_times_the_price_scores_nothing():
    """#L139 promises the formula is "never zero, so even a bad guess can be ranked".
    It is not: exp underflows at a deviation of ~2.303, which is a ratio of ~3.30, the
    same multiple all along the band - so every wild high guess scores the same 0 as
    not playing at all (#L151) and cannot be ranked against another.
    """
    assert points(3303, 1000) == 1
    assert points(3304, 1000) == 0
    assert points(20_000, 500) == 0                # both values are inside PRICE_BAND
    assert points(66_073, 20_000) == 0


def test_a_far_off_low_guess_still_banks_ten():
    """The other half of the same asymmetry: deviation from below cannot pass 1, because
    a price has a floor at 1 CZK, so guessing the minimum is worth exactly 10 points on
    any listing - which is the guess the roadmap's own argument (#L136) wanted dead.
    """
    for real in REALS:
        assert points(1, real) == 10, f"points(1, {real})"
        assert points(4 * real, real) == 0         # and 0 < 10: the bad low guess wins


def test_zero_real_price_is_guarded_by_the_schema_not_by_scoring():
    """P-012 / Q-006 - nothing in scoring() guards the denominator. CHECK (price > 0)
    in schema.py is what keeps 0 out of the column. Pinned so that the day a guard is
    added here, this test is the thing that says so out loud.
    """
    with pytest.raises(ZeroDivisionError):
        points(1500, 0)
