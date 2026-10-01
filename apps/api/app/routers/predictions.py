from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.prediction import (
    PredictionRequest,
    PredictionResponse,
    PreferenceListRequest,
    PreferenceListResponse,
)
from app.services.prediction_service import generate_preference_list, predict

router = APIRouter(prefix="/api", tags=["predictions"])


@router.post("/predict/jee", response_model=PredictionResponse)
def predict_jee(payload: PredictionRequest, db: Session = Depends(get_db)) -> PredictionResponse:
    return predict(db, payload)


@router.post("/predict/neet", response_model=PredictionResponse)
def predict_neet(payload: PredictionRequest, db: Session = Depends(get_db)) -> PredictionResponse:
    return predict(db, payload)


@router.post("/counselling/preference-list", response_model=PreferenceListResponse)
def preference_list(payload: PreferenceListRequest, db: Session = Depends(get_db)) -> PreferenceListResponse:
    return generate_preference_list(db, payload)
