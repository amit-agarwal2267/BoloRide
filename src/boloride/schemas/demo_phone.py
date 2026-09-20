from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DemoPhonePublicResponse(BaseModel):
    masked_number: str
    in_use: bool


class DemoPhoneCallStartResponse(BaseModel):
    phone_number: str
    masked_number: str
    call_id: UUID
    expires_at: datetime


class DemoPhoneCallEndRequest(BaseModel):
    call_id: UUID
