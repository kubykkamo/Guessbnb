"""USERS table. Hesla se neukládají, identita jde přes Auth0 ID."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    auth0_id: str = Field(..., min_length=1, max_length=128, description="Unikátní ID z Auth0 (Unique)")
    username: str = Field(..., min_length=1, max_length=30, description="Zobrazované jméno")


class User(UserCreate):
    id: int
    global_score: int = Field(0, ge=0, description="Kumulativní skóre")
    created_at: datetime
