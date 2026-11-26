from pprint import pprint
from src.game.state import SubmitGuess, RoundEnded, RoundStarted, StartGame, Listing, DeadlineReached, \
    GameFinished, Phase, SetSettings, NextRound


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

    # pprint(events_p2)


# --- three more from the list: arrange + act are yours, the asserts are fixed.
# Names the asserts expect you to bind: room, events, scores_before, in_lobby,
# in_round, ghost. Until you fill them in each of these fails with NameError -
# that red is the hole, not a bug.


async def test_full_game_reaches_game_over(room_with_two_players):
    """_advance()'s finish branch has never run in a test - nothing here proves a game
    can end. Play at least two rounds, so REVEALING -> ROUND_OPEN is walked and not
    just the last hop.
    """
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700),
                              Listing(id="2", city="Brno", price=2400),
                              Listing(id="3", city="Brno", price=2100)]

    await room.handle(SetSettings(player_id="p1", city="Brno", rounds=3))

    await room.handle(StartGame(player_id="p1", listings=dummy_listings))




    await room.handle(SubmitGuess(player_id="p1", round=room.round_token, price=1800))
    await room.handle(SubmitGuess(player_id="p2", round=room.round_token, price=2000))

    await room.handle(NextRound("p1"))

   

    await room.handle(SubmitGuess(player_id="p1", round=room.round_token, price=1900))
    await room.handle(SubmitGuess(player_id="p2", round=room.round_token, price=2100))

    await room.handle(NextRound("p1"))


    await room.handle(SubmitGuess(player_id="p1", round=room.round_token, price=1500))
    await room.handle(SubmitGuess(player_id="p2", round=room.round_token, price=1400))

    events = await room.handle(NextRound("p1"))

    # ARRANGE - settings (host only, LOBBY), a draw big enough for the round count, start
    # ACT     - play every round to the very end; bind the events of the LAST handle()
    #           call to `events`
    # pprint(events)

    assert isinstance(events[-1], GameFinished)
    assert room.phase is Phase.GAME_OVER
    assert room.round_no == room.rounds_total        # all of them really played
    assert room.round_no >= 2                        # more than one round, on purpose
    assert events[-1].persisted is False             # F5 is what flips this
    assert len(events[-1].standings) == 2
    assert all(s["score"] == room.players[s["player_id"]].score
               for s in events[-1].standings)        # standings agree with the seats
    assert [s["score"] for s in events[-1].standings] == sorted(
        (s["score"] for s in events[-1].standings), reverse=True)   # ranked

    #MUTATION - name the one line in state.py that, changed, turns this red.


async def test_stale_deadline_is_discarded(room_with_two_players):
    """#L65 - a timer carrying an old round's token is discarded rather than answered.
    Get into round 2 the way the game really does; P-021 forbids assigning a token by
    hand.
    """
    room = room_with_two_players


    # ARRANGE - reach round 2 for real, then remember the scores in `scores_before`

    token = room.round_token
    
    dummy_listings = [Listing(id="1", city="Brno", price=1700),
                                  Listing(id="2", city="Brno", price=2400),
                                  Listing(id="3", city="Brno", price=2100)]
    
    await room.handle(StartGame(player_id="p1", listings=dummy_listings))
    round1_token = room.round_token  # až po startu 1. kola

    await room.handle(SubmitGuess(player_id="p1", round=round1_token, price=1900))
    await room.handle(SubmitGuess(player_id="p2", round=round1_token, price=2100))
    await room.handle(NextRound(player_id="p1"))  # teď jsi reálně ve 2. kole

    scores_before = {p.player_id: p.score for p in room.players.values()}
    events = await room.handle(DeadlineReached(round1_token))
    pprint(events)
    
    


    # ACT     - send the DEADLINE of round 1 and bind its events to `events`

    assert events == []                              # not [Error(...)], not [RoundEnded]
    assert room.round_no == 2
    assert room.round_token == 2                     # a counter: once per round opened
    assert {p.player_id: p.score for p in room.players.values()} == scores_before

    # MUTATION - name the one line in state.py that, changed, turns this red.


async def test_guard_precedence(room_with_two_players):
    """Which guard wins when two conditions are bad at once. P-023: 5f476bb changed
    this order silently and no test protested - one test, because the matrix is the
    thing that regressed, not the individual codes.
    """
    room = room_with_two_players
    dummy_listings = [Listing(id="1", city="Brno", price=1700),
                                      Listing(id="2", city="Brno", price=2400),
                                      Listing(id="3", city="Brno", price=2100)]

    # ACT 1 - p2 (seated, not host) sends set_settings while still in LOBBY -> `in_lobby`
    in_lobby = await room.handle(SetSettings(player_id="p2", city="Brno",  rounds=3))
    # ACT 2 - start the game, then send that same command again in ROUND_OPEN -> `in_round`
    await room.handle(StartGame(player_id="p1", listings=dummy_listings))
    in_round = await room.handle(SetSettings(player_id="p2", city="Brno", rounds=3))
    # ACT 3 - a player_id nobody has ever seated guesses in ROUND_OPEN       -> `ghost`
    ghost = await room.handle(SubmitGuess(player_id="aaa", round=room.round_token, price=2000))
    assert in_lobby[-1].code == "NOT_HOST"           # phase passed, the host check stopped it
    assert in_round[-1].code == "INVALID_STATE"      # phase is checked FIRST for this command...
    assert ghost[-1].code == "NOT_SEATED"            # ...but the player is checked first for that one
    assert room.phase is Phase.ROUND_OPEN            # none of the three moved the machine
    assert room.players["p2"].score == 0

    # MUTATION - name the one line in state.py that, changed, turns this red.


