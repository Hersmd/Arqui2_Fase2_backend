from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

class State(BaseModel):
    # Campos base (compatibles con la UI actual)
    parking: List[bool] = Field(default_factory=list)
    door: str = "unknown"  # open|closed|unknown
    barrier: str = "unknown"  # up|down|unknown
    conveyor: str = "unknown"  # running|stopped|on|off|unknown (principal)
    lighting: str = "unknown"  # on|off|auto|unknown
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Extensiones (para reflejar maqueta completa)
    conveyor_principal: Optional[str] = None
    conveyor_plastico: Optional[str] = None
    conveyor_vidrio: Optional[str] = None
    conveyor_metal: Optional[str] = None

    bin_plastico_full: Optional[bool] = None
    bin_vidrio_full: Optional[bool] = None
    bin_metal_full: Optional[bool] = None

    smoke_alarm: Optional[bool] = None
    emergency: Optional[bool] = None