"""LISTINGS table - ubytování importované ETL skriptem."""

from pydantic import BaseModel, Field


class ListingCreate(BaseModel):
    external_id: str = Field(..., min_length=1, max_length=64, description="ID z Inside Airbnb (Unique)")
    city: str = Field(..., min_length=1, max_length=64, description="Filtr (Praha, Vídeň...)")
    name: str = Field(..., min_length=1, max_length=200, description="Název (např. Cozy Apartment)")
    property_type: str = Field(..., min_length=1, max_length=64, description="Typ (Entire home, Room)")
    accommodates: int = Field(..., ge=1, description="Kapacita osob")
    bedrooms: int | None = Field(None, ge=0, description="Počet ložnic")
    rating: float | None = Field(None, ge=0, le=5, description="Průměrné hodnocení (např. 4.85)")
    reviews_count: int = Field(0, ge=0, description="Počet hodnocení")
    price: float = Field(..., gt=0, description="Cílová cena za noc")


class Listing(ListingCreate):
    id: int
