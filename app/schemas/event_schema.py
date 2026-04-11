from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Event(BaseModel):
    type: str
    material: Optional[str]
    result: Optional[str]
    line: Optional[str]
    timestamp: datetime