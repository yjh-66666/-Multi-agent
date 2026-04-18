from __future__ import annotations

from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

PreferenceType = Literal["cheap", "fast", "comfy", "foodie", "family"]

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    code: str = "ok"
    message: str = "success"
    request_id: str = "-"
    data: Optional[T] = None


class HotelRequirements(BaseModel):
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_score: Optional[float] = 4.0


class FoodPreferences(BaseModel):
    tastes: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    budget_per_person: Optional[float] = None


class TripQuery(BaseModel):
    origin: str = Field(description="例如：南京")
    destination: str = Field(description="例如：长沙")
    depart_date: str = Field(description="yyyy-MM-dd")
    people_count: int = 1
    preference: PreferenceType = "fast"
    hotel_requirements: HotelRequirements = Field(default_factory=HotelRequirements)
    food_preferences: FoodPreferences = Field(default_factory=FoodPreferences)


class TrainTicketItem(BaseModel):
    train_code: str
    start_time: str
    arrive_time: str
    duration: str
    from_station: str
    to_station: str
    business_seat: str = "-"
    first_class: str = "-"
    second_class: str = "-"
    no_seat: str = "-"
    score: float = 0.0


class PoiItem(BaseModel):
    name: str
    address: str = ""
    distance_m: Optional[int] = None
    score: float = 4.5
    tags: List[str] = Field(default_factory=list)


class TripPlanResponse(BaseModel):
    route_summary: str
    classic_train: Optional[TrainTicketItem] = None
    all_trains: List[TrainTicketItem] = Field(default_factory=list)
    nearby_hotels: List[PoiItem] = Field(default_factory=list)
    nearby_foods: List[PoiItem] = Field(default_factory=list)
    nearby_attractions: List[PoiItem] = Field(default_factory=list)
    analysis: Dict[str, Any] = Field(default_factory=dict)
    tips: List[str] = Field(default_factory=list)
