from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from boloride.schemas.location import LocationSchema


class RideBookingSchema(BaseModel):
	model_config = ConfigDict(extra="forbid")

	user_id: UUID
	pickup: LocationSchema
	destination: LocationSchema
	requested_ride_at: datetime
	ride_type: str = "standard"
	confirmed: bool = False
