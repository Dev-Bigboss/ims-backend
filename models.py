from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Activity(BaseModel):
    action: str
    entityType: str
    entityId: str
    details: str
    userId: Optional[str] = None
    createdAt: datetime = datetime.utcnow()

    class Config:
        from_attributes = True  # Allow conversion from MongoDB documents