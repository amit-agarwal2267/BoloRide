from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LocationSchema(BaseModel):
	model_config = ConfigDict(extra="forbid")

	display_name: str | None = None
	formatted_address: str = Field(min_length=1)
	latitude: Decimal = Field(ge=-90, le=90)
	longitude: Decimal = Field(ge=-180, le=180)
	provider: str | None = None
	provider_place_id: str | None = None
