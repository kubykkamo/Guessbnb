from pprint import pprint
from src.game.state import SubmitGuess, RoundEnded, RoundStarted, StartGame, Listing, DeadlineReached


async def test_two_players_submit_ends_round(room_with_two_players):
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700)]

    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    token = room.round_token

    events_p1 = await room.handle(SubmitGuess(player_id="p1", round=token, price=1800))

    events_p2 = await room.handle(SubmitGuess(player_id="p2", round=token, price=2000))

    assert isinstance(events_p2[-1], RoundEnded)

    # print("--- P1 EVENTS ---")
    # pprint(events_p1)
    # print ("--- P2 EVENTS ---")
    # pprint(events_p2)
    round_ended = events_p2[-1]
    # print("--- RESULT EVENT ---")
    # pprint(round_ended)
    # print("--- RESULTS ---")
    # pprint(round_ended.results)


    assert len(round_ended.results) == 2

async def test_only_one_of_two_submits_round_ends(room_with_two_players):
    room = room_with_two_players

    # two listings, so the reveal timer at the end can open round 2 instead of
    # running out of drawn ones
    dummy_listings = [Listing(id="1", city="Brno", price=1700),
                      Listing(id="2", city="Brno", price=2400)]

    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    token = room.round_token

    await room.handle(SubmitGuess(player_id="p1", round=token, price=1800))

    room.clock.advance(30)                                    # ROUND_SECONDS

    events = await room.handle(DeadlineReached(token=token))

    assert isinstance(events[-1], RoundEnded)

    # takes the result of the player who never guessed
    p2_result = next(r for r in events[-1].results if r["player_id"] == "p2")

    assert p2_result["points"] == 0                           # no guess = 0 points (#L151)

    # "EVALUATES EXACTLY ONCE" (#L181) - nothing that arrives after the evaluation may
    # score the round again, neither the guess that lost the race nor the reveal timer.
    late_guess = await room.handle(SubmitGuess(player_id="p2", round=token, price=9999))
    reveal_timer = await room.handle(DeadlineReached(token=token))

    assert late_guess[-1].code == "INVALID_STATE"             # we are in REVEALING already
    assert isinstance(reveal_timer[-1], RoundStarted)         # the timer opened round 2...
    assert len([e for e in events + late_guess + reveal_timer
                if isinstance(e, RoundEnded)]) == 1           # ...without scoring round 1 twice
    assert room.players["p2"].score == 0                      # and scored nothing for him

async def test_old_guess_doesnt_change_score_stale_round(room_with_two_players):
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700),
                      Listing(id="2", city="Brno", price=2400)]

    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    round1_token = room.round_token

    # reach round 2 the way the game really does, so the guess carries a token
    # round 2 genuinely rejects instead of one we invented for the test
    await room.handle(SubmitGuess(player_id="p1", round=round1_token, price=1700))
    room.clock.advance(30)
    await room.handle(DeadlineReached(token=round1_token))     # round 1 evaluated, REVEALING
    await room.handle(DeadlineReached(token=room.round_token)) # reveal timer -> round 2 opens

    assert room.round_no == 2
    assert room.round_token != round1_token                    # a real new token, not a fake one

    scores_before = {p.player_id: p.score for p in room.players.values()}
    guesses_before = dict(room.guesses)

    events = await room.handle(SubmitGuess(player_id="p2", round=round1_token, price=1700))

    assert events[-1].code == "STALE_ROUND"
    assert {p.player_id: p.score for p in room.players.values()} == scores_before
    assert room.guesses == guesses_before                      # nothing was stored either (#L182)

async def test_second_start_equals_invalid_state(room_with_two_players):
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700)]

    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    event2 = await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    assert event2[-1].code == "INVALID_STATE"

async def test_guess_at_deadline_instant_evaluates_once(room_with_two_players):
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700),
                          Listing(id="2", city="Brno", price=2400)]
    
    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    token = room.round_token

    await room.handle(SubmitGuess(player_id="p1", round=token, price=1800))

    room.clock.advance(30)
    
    events_p2 = await room.handle(SubmitGuess(player_id="p2", round=token, price=2000))

    events_p3 = await room.handle(DeadlineReached(token=token))

    assert isinstance(events_p2[-1], RoundEnded)
    p2_result = next(r for r in events_p2[-1].results if r["player_id"] == "p2")
    assert p2_result["points"] == 67
    
        # evaluated exactly once (#L181) - the timer that lost the race must not score it again
    assert len([e for e in events_p2 + events_p3 if isinstance(e, RoundEnded)]) == 1
    assert room.players["p2"].score == 67  

    pprint(events_p2)


