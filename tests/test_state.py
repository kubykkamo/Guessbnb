import conftest
from src.game.state import SubmitGuess, RoundEnded, StartGame, Listing

async def test_two_players_submit_ends_round(room_with_two_players):
    room = room_with_two_players
    
    dummy_listings = [Listing(id="1", city="Brno", price=1500)]
    
    await room.handle(StartGame(player_id="p1", listings=dummy_listings))
    
    token = room.round_token
    
    events_p1 = await room.handle(SubmitGuess(player_id="p1", round=token, price=1000))
    
    events_p2 = await room.handle(SubmitGuess(player_id="p2", round=token, price=2000))
    
    assert isinstance(events_p2[-1], RoundEnded)
    
    round_ended = events_p2[-1]
    assert len(round_ended.results) == 2
    
    