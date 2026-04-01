from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.crud import transaction as crud_transaction
from app.database import get_db
from app.schemas.transaction import TransactionResponse
from app.services.csv_parser import parse_csv
from app.services.pdf_parser import parse_pdf

router = APIRouter(prefix="/upload", tags=["upload"])

_CONTENT_TYPE_MAP: dict[str, str] = {
    "text/csv": "csv",
    "application/csv": "csv",
    "application/pdf": "pdf",
}


def _detect_file_type(filename: str, content_type: str) -> str | None:
    """Return 'csv' or 'pdf' based on content-type header or file extension."""
    if content_type in _CONTENT_TYPE_MAP:
        return _CONTENT_TYPE_MAP[content_type]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "csv":
        return "csv"
    if ext == "pdf":
        return "pdf"
    return None


@router.post(
    "/",
    response_model=list[TransactionResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV or PDF file and import transactions",
)
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> list[TransactionResponse]:
    file_type = _detect_file_type(file.filename or "", file.content_type or "")
    if file_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Please upload a CSV or PDF file.",
        )

    content = await file.read()

    try:
        if file_type == "csv":
            transactions = parse_csv(content)
        else:
            transactions = parse_pdf(content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse {file_type.upper()} file: {exc}",
        ) from exc

    return [crud_transaction.create_transaction(db, t) for t in transactions]
