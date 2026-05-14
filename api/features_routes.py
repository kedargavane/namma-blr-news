"""
api/features_routes.py — Feature request endpoints.

GET  /api/features           — list all (any logged-in user)
POST /api/features           — submit new request (any logged-in user)
PATCH /api/features/{id}     — admin: update status + comment
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from api.auth import get_current_user, get_admin_user

router = APIRouter()


def serialize_feature(f, session) -> dict:
    from db.models import User
    submitter_name = None
    if f.submitted_by:
        u = session.query(User).filter_by(id=f.submitted_by).first()
        if u:
            submitter_name = u.name
    return {
        "id":            f.id,
        "title":         f.title,
        "description":   f.description,
        "status":        f.status,
        "admin_comment": f.admin_comment,
        "submitted_by":  f.submitted_by,
        "submitter_name": submitter_name,
        "created_at":    f.created_at.isoformat() if f.created_at else None,
        "updated_at":    f.updated_at.isoformat() if f.updated_at else None,
    }


def get_engine_session():
    """Imported at call time to avoid circular imports."""
    from db.models import get_engine, get_session
    from config import CONFIG
    engine = get_engine(CONFIG["db_path"])
    return get_session(engine)


@router.get("/api/features")
def list_features(current_user: dict = Depends(get_current_user)):
    session = get_engine_session()
    try:
        from db.models import FeatureRequest
        rows = session.query(FeatureRequest).order_by(
            FeatureRequest.created_at.desc()
        ).all()
        return {"features": [serialize_feature(r, session) for r in rows]}
    finally:
        session.close()


@router.post("/api/features")
def submit_feature(body: dict, current_user: dict = Depends(get_current_user)):
    title       = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if len(title) > 200:
        raise HTTPException(status_code=400, detail="Title must be under 200 characters")

    session = get_engine_session()
    try:
        from db.models import FeatureRequest
        user_id = int(current_user["sub"])
        row = FeatureRequest(
            title=title,
            description=description,
            status="submitted",
            submitted_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return serialize_feature(row, session)
    finally:
        session.close()


@router.patch("/api/features/{feature_id}")
def update_feature(
    feature_id: int,
    body: dict,
    admin: dict = Depends(get_admin_user)
):
    session = get_engine_session()
    try:
        from db.models import FeatureRequest
        row = session.query(FeatureRequest).filter_by(id=feature_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Feature request not found")

        valid_statuses = {"submitted", "under_review", "in_progress", "completed", "declined"}
        if "status" in body:
            if body["status"] not in valid_statuses:
                raise HTTPException(status_code=400, detail=f"Invalid status. Choose from: {valid_statuses}")
            row.status = body["status"]

        if "admin_comment" in body:
            row.admin_comment = (body["admin_comment"] or "").strip()

        row.updated_at = datetime.utcnow()
        session.commit()
        return serialize_feature(row, session)
    finally:
        session.close()


@router.delete("/api/features/{feature_id}")
def delete_feature(
    feature_id: int,
    admin: dict = Depends(get_admin_user)
):
    session = get_engine_session()
    try:
        from db.models import FeatureRequest
        row = session.query(FeatureRequest).filter_by(id=feature_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        session.delete(row)
        session.commit()
        return {"message": "deleted"}
    finally:
        session.close()
