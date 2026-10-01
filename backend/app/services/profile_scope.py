"""Profile ownership: snapshot at creation, infer legacy rows from unique service IDs."""
from __future__ import annotations

from app.services.taxonomy import get_profile_services, get_tracks
from sqlalchemy import and_, or_


def service_profile_id(service_id: str) -> str | None:
    matches = {track["id"] for track in get_tracks().get("tracks", [])
               for service in track.get("services", []) if service.get("id") == service_id}
    return next(iter(matches)) if len(matches) == 1 else None


def record_profile_id(record: object) -> str | None:
    return getattr(record, "profile_id", None) or service_profile_id(getattr(record, "service_id", ""))


def current_profile_id(db, user_id: str) -> str | None:
    from app.models import User

    user = db.get(User, user_id)
    return user.current_profile if user else None


def service_in_profile(service_id: str, profile_id: str | None) -> bool:
    return bool(profile_id and service_id in {item["id"] for item in get_profile_services(profile_id)})


def profile_filter(model, profile_id: str):
    """SQL predicate including only unambiguous unmigrated legacy rows."""
    legacy_ids = [item["id"] for item in get_profile_services(profile_id)
                  if service_profile_id(item["id"]) == profile_id]
    missing = or_(model.profile_id.is_(None), model.profile_id == "")
    return or_(model.profile_id == profile_id,
               and_(missing, model.service_id.in_(legacy_ids)))
