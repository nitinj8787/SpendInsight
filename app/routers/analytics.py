from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.crud import analytics
from app.database import get_db
from app.schemas.analytics import AnalyticsResponse

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/", response_model=AnalyticsResponse)
def get_analytics(db: Session = Depends(get_db)):
    return analytics.get_analytics(db)
