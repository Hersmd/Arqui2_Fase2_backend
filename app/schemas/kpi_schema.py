from pydantic import BaseModel

class KPI(BaseModel):
    date: str
    plastic: int
    glass: int
    metal: int
    rejects: int
    throughput: int