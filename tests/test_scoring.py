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
