from pydantic import BaseModel
from datetime import datetime

class Alert(BaseModel):
    type: str
    description: str
    timestamp: datetime