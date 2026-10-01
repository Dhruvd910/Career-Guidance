from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_student_profile
from app.models.saved_item import SavedItem
from app.models.student import StudentProfile
from app.schemas.saved_item import SavedItemCreate, SavedItemOut

router = APIRouter(prefix="/api/saved-items", tags=["saved-items"])


@router.get("", response_model=list[SavedItemOut])
def list_saved_items(
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> list[SavedItemOut]:
    return db.query(SavedItem).filter(SavedItem.student_profile_id == profile.id).all()


@router.post("", response_model=SavedItemOut, status_code=201)
def create_saved_item(
    payload: SavedItemCreate,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> SavedItemOut:
    item = SavedItem(student_profile_id=profile.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_saved_item(
    item_id: int,
    profile: StudentProfile = Depends(get_current_student_profile),
    db: Session = Depends(get_db),
) -> None:
    item = (
        db.query(SavedItem)
        .filter(SavedItem.id == item_id, SavedItem.student_profile_id == profile.id)
        .first()
    )
    if item:
        db.delete(item)
        db.commit()
