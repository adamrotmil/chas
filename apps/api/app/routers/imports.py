from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.schemas import DriveImportRequest, DriveImportResponse
from app.services.drive_import import import_drive_file

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/drive", response_model=DriveImportResponse)
def import_drive_files(
    payload: DriveImportRequest,
    session: Session = Depends(get_session),
) -> DriveImportResponse:
    if not payload.files:
        raise HTTPException(status_code=400, detail="At least one Drive file is required.")
    if len(payload.files) > 50:
        raise HTTPException(status_code=400, detail="Import at most 50 Drive files at a time.")

    try:
        imported = [
            import_drive_file(
                session,
                file,
                imported_by=payload.imported_by,
                create_triage_tasks=payload.create_triage_tasks,
            )
            for file in payload.files
        ]
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session.commit()
    return DriveImportResponse(
        imported=imported,
        created_count=sum(1 for item in imported if item.created),
        existing_count=sum(1 for item in imported if not item.created),
    )
