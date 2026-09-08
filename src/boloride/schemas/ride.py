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
	passenger_count: int = 1
	selected_vehicle_type_code: str
	confirmed: bool = False
