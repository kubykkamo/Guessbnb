"""LISTINGS table - ubytování importované ETL skriptem."""

from pydantic import BaseModel, Field


class ListingCreate(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=64, description="ID z Inside Airbnb (Unique)")
    city: str = Field(..., min_length=1, max_length=64, description="Filtr (Prague, New York...)")
    country: str = Field(..., min_length=1, max_length=64, description="Země pro štítek na kartě (Czechia, United States)")
    neighbourhood: str | None = Field(None, max_length=64, description="Čtvrť (Praha 1…22, Libuš…)")
    latitude: float | None = Field(None, ge=-90, le=90, description="Šířka z CSV (na mapu, ne na měření)")
    longitude: float | None = Field(None, ge=-180, le=180, description="Délka z CSV (na mapu, ne na měření)")
    name: str = Field(..., min_length=1, max_length=200, description="Název (např. Cozy Apartment)")
    property_type: str = Field(..., min_length=1, max_length=64, description="Typ (Entire home, Room)")
    room_type: str = Field(..., min_length=1, max_length=64, description="Entire home/apt / Private room / Shared room / Hotel room")
    accommodates: int = Field(..., ge=1, description="Kapacita osob")
    bedrooms: int | None = Field(None, ge=0, description="Počet ložnic")
    beds: int | None = Field(None, ge=0, description="Počet postelí")
    bathrooms: float | None = Field(None, ge=0, description="Počet koupelen (1,5 = 1+1 napůl)")
    rating: float | None = Field(None, ge=0, le=5, description="Průměrné hodnocení (např. 4.85)")
    reviews_count: int = Field(0, ge=0, description="Počet hodnocení")
    price: float = Field(..., gt=0, description="Cílová cena za noc")


class Listing(ListingCreate):
    id: int
