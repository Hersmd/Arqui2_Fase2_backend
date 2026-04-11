from pydantic import BaseModel
from typing import List
from datetime import datetime

class State(BaseModel):
    parking: List[bool]
    door: str
    barrier: str
    conveyor: str
    lighting: str
    timestamp: datetime