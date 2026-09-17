from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DemoAccessResponse(BaseModel):
    status: Literal[
        "not_requested",
        "waitlisted",
        "approved",
    ]

    position: int | None = None

    granted_at: datetime | None = None