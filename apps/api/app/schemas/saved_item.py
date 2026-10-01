from datetime import datetime

from pydantic import BaseModel


class SavedItemCreate(BaseModel):
    item_type: str  # college | branch | career | course
    item_id: int
    bucket: str | None = None  # dream | target | safe
    notes: str | None = None


class SavedItemOut(SavedItemCreate):
    id: int
    student_profile_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
