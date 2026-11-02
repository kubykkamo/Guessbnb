"""PHOTOS table - links to photos in S3/R2, never the photo data."""

from pydantic import BaseModel, Field


class PhotoCreate(BaseModel):
    listing_id: int = Field(..., gt=0, description="Vazba na ubytování (LISTINGS.id)")
    image_url: str = Field(..., min_length=1, max_length=2048, description="Odkaz na S3/R2 úložiště")
    display_order: int = Field(..., ge=1, description="Pořadí zobrazení (1, 2, 3...)")


class Photo(PhotoCreate):
    id: int
