"""Input/output schemas for PocketSmart AI."""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field


class RegisterUser(BaseModel):
    username: str = Field(min_length=3, max_length=30, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    full_name: Optional[str] = None
    password: str = Field(min_length=6, max_length=72)


class UserInDB(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None
    hashed_password: str
    disabled: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str


class UserSession(BaseModel):
    username: str
    login_time: datetime
    last_activity: datetime
    token: str
    user_data: Dict[str, Any] = {}


class HomeBudgetInput(BaseModel):
    total_budget: float = Field(gt=0)
    num_lights: int = Field(default=0, ge=0, le=200)
    num_fans: int = Field(default=0, ge=0, le=100)
    num_furniture: int = Field(default=0, ge=0, le=200)
    num_dining_tables: int = Field(default=0, ge=0, le=50)
    has_living_room: bool = False
    has_kitchen: bool = False
    has_bedroom: bool = False
    additional_requirements: Optional[str] = None


class PartyBudgetInput(BaseModel):
    total_budget: float = Field(gt=0)
    num_guests: int = Field(gt=0, le=5000)
    party_type: str
    venue_type: Optional[str] = None
    needs_catering: bool = False
    needs_decoration: bool = False
    needs_entertainment: bool = False
    additional_requirements: Optional[str] = None


class JewelryBudgetInput(BaseModel):
    total_budget: float = Field(gt=0)
    occasion: str
    preferences: Optional[str] = None


class RecommendationHistory(BaseModel):
    id: str
    timestamp: str
    username: str
    recommendation_type: str
    input_data: Dict[str, Any]
    summary: Dict[str, Any]
    full_result: Dict[str, Any]
