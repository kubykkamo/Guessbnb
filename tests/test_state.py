import conftest
from pprint import pprint
from src.game.state import SubmitGuess, RoundEnded, StartGame, Listing, DeadlineReached


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

    room.clock = conftest.FakeClock()
    
    dummy_listings = [Listing(id="1", city="Brno", price=1700)]
    
    await room.handle(StartGame(player_id="p1", listings=dummy_listings))
    
    token = room.round_token

    submit = await room.handle(SubmitGuess(player_id="p1", round=token, price=1800))
    
    room.clock.advance(30)

    events = await room.handle(DeadlineReached(token=token))

    assert isinstance(events[-1], RoundEnded)

    # finds a a takes the first player in results of a dictionary player_id value p2
    p2_result = next(r for r in events[-1].results if r["player_id"] == "p2")

    assert p2_result["points"] == 0
    

        
async def test_old_guess_doesnt_change_score_stale_round(room_with_two_players):
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700)]

    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    token = room.round_token

    last_score = room.players["p1"].score

    room.round_token = "round2_token"

    events = await room.handle(SubmitGuess(player_id="p1", round=token, price=1700))

    assert events[-1].code == "STALE_ROUND"
    assert room.players["p1"].score == last_score
    
async def test_second_start_equals_invalid_state(room_with_two_players):
    room = room_with_two_players

    dummy_listings = [Listing(id="1", city="Brno", price=1700)]
    
    await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    event2 = await room.handle(StartGame(player_id="p1", listings=dummy_listings))

    assert event2[-1].code == "INVALID_STATE"
