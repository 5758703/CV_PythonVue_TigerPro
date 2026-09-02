"""MTMC P0 持久化：Global 身份、Tracklet、Association 证据。"""
from __future__ import annotations

import json
import logging
from datetime import datetime

log = logging.getLogger(__name__)


def _utc_now():
    return datetime.utcnow()


def persist_global_identity(app, gtrack, *, session_id: str | None = None) -> None:
    """写入/更新 MtmcGlobalPerson 或 MtmcGlobalVehicle。"""
    if app is None or gtrack is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcGlobalPerson, MtmcGlobalVehicle

            now = _utc_now()
            gid = gtrack.global_id
            if gtrack.object_type == "person":
                row = MtmcGlobalPerson.query.filter_by(global_id=gid).first()
                if row is None:
                    row = MtmcGlobalPerson(global_id=gid, first_seen_at=now)
                    db.session.add(row)
                if gtrack.reid_person_id:
                    row.reid_person_id = gtrack.reid_person_id
                if gtrack.face_person_id:
                    row.face_person_id = gtrack.face_person_id
                if gtrack.display_name:
                    row.display_name = gtrack.display_name
                row.last_seen_at = now
                row.status = "0"
            else:
                row = MtmcGlobalVehicle.query.filter_by(global_id=gid).first()
                if row is None:
                    row = MtmcGlobalVehicle(global_id=gid, first_seen_at=now)
                    db.session.add(row)
                if gtrack.plate:
                    row.plate = gtrack.plate
                if gtrack.visual_key:
                    row.visual_key = gtrack.visual_key
                if gtrack.identity_key:
                    row.identity_key = gtrack.identity_key
                row.last_seen_at = now
                row.status = "0"
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist global identity failed: %s", e)


def persist_tracklet(app, builder, *, global_id: str | None = None) -> None:
    if app is None or builder is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcTracklet

            summary = builder.summary()
            row = MtmcTracklet.query.filter_by(tracklet_id=builder.tracklet_id).first()
            if row is None:
                row = MtmcTracklet(tracklet_id=builder.tracklet_id)
                db.session.add(row)
            row.session_id = builder.session_id
            row.camera_id = builder.camera_id
            row.object_type = builder.object_type
            row.local_track_id = builder.local_track_id
            row.global_id = global_id or builder.assigned_global_id
            row.start_time = datetime.utcfromtimestamp(builder.start_ts) if builder.start_ts else _utc_now()
            row.end_time = datetime.utcfromtimestamp(builder.end_ts) if builder.end_ts else _utc_now()
            row.keyframe_count = int(summary.get("keyframeCount") or 0)
            row.observation_count = int(summary.get("observationCount") or 0)
            row.avg_quality = float(summary.get("avgQuality") or 0)
            row.embedding_dim = int(summary.get("embeddingDim") or 0)
            row.status = "associated" if row.global_id else "closed"
            row.trail_json = json.dumps(summary.get("trail") or [])
            row.attrs_json = json.dumps(summary)
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist tracklet failed: %s", e)


def persist_association_edge(
    app,
    *,
    session_id: str,
    tracklet_id: str | None,
    object_type: str,
    decision: str,
    target_global_id: str,
    source_global_id: str | None = None,
    scores: dict | None = None,
    evidence: dict | None = None,
    policy_version: str = "mtmc_v1",
) -> None:
    if app is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcAssociationEdge

            row = MtmcAssociationEdge(
                session_id=session_id,
                tracklet_id=tracklet_id,
                object_type=object_type,
                decision=decision,
                source_global_id=source_global_id,
                target_global_id=target_global_id,
                policy_version=policy_version,
                scores_json=json.dumps(scores or {}, ensure_ascii=False),
                evidence_json=json.dumps(evidence or {}, ensure_ascii=False),
            )
            db.session.add(row)
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist association edge failed: %s", e)


def persist_cross_camera_event(
    app,
    *,
    session_id: str,
    global_id: str,
    object_type: str,
    from_camera_id: int,
    to_camera_id: int,
    transit_sec: float | None = None,
    display_name: str | None = None,
    plate: str | None = None,
    decision: str | None = None,
    attrs: dict | None = None,
    event_time: datetime | None = None,
) -> None:
    if app is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcCrossCameraEvent

            row = MtmcCrossCameraEvent(
                session_id=session_id,
                global_id=global_id,
                object_type=object_type,
                from_camera_id=int(from_camera_id),
                to_camera_id=int(to_camera_id),
                transit_sec=transit_sec,
                display_name=display_name,
                plate=plate,
                decision=decision,
                event_time=event_time or _utc_now(),
                attrs_json=json.dumps(attrs or {}, ensure_ascii=False),
            )
            db.session.add(row)
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist cross camera event failed: %s", e)


def persist_candidate_pair(
    app,
    *,
    session_id: str,
    global_id: str,
    candidate_global_id: str,
    object_type: str,
    camera_id: int | None = None,
    tracklet_id: str | None = None,
    final_score: float | None = None,
    reid_score: float | None = None,
    evidence: dict | None = None,
) -> None:
    if app is None:
        return
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import MtmcCandidatePair

            existing = (
                MtmcCandidatePair.query.filter_by(
                    session_id=session_id,
                    global_id=global_id,
                    candidate_global_id=candidate_global_id,
                    status="pending",
                ).first()
            )
            if existing is not None:
                return
            row = MtmcCandidatePair(
                session_id=session_id,
                global_id=global_id,
                candidate_global_id=candidate_global_id,
                object_type=object_type,
                camera_id=camera_id,
                tracklet_id=tracklet_id,
                status="pending",
                final_score=final_score,
                reid_score=reid_score,
                evidence_json=json.dumps(evidence or {}, ensure_ascii=False),
            )
            db.session.add(row)
            db.session.commit()
    except Exception as e:  # noqa: BLE001
        log.debug("persist candidate pair failed: %s", e)


def resolve_candidate_pair(
    app,
    *,
    session_id: str,
    global_id: str,
    candidate_global_id: str,
    status: str,
) -> bool:
    if app is None:
        return False
    try:
        with app.app_context():
            from extensions import db
            from models.mtmc import (
                MtmcAssociationEdge, MtmcCandidatePair, MtmcCrossCameraEvent,
                MtmcGlobalPerson, MtmcGlobalVehicle, MtmcTrackEvent,
                MtmcTracklet, MtmcVehiclePass,
            )

            rows = (
                MtmcCandidatePair.query.filter_by(
                    session_id=session_id,
                    global_id=global_id,
                    candidate_global_id=candidate_global_id,
                    status="pending",
                ).all()
            )
            if not rows:
                return False
            resolved_at = _utc_now()
            for row in rows:
                row.status = status
                row.resolve_time = resolved_at
            if status == "promoted":
                def replace_global(persisted_rows, *fields):
                    for persisted_row in persisted_rows:
                        for field in fields:
                            if getattr(persisted_row, field) == global_id:
                                setattr(persisted_row, field, candidate_global_id)

                replace_global(MtmcCandidatePair.query.filter_by(session_id=session_id).all(), "global_id", "candidate_global_id")
                replace_global(MtmcTracklet.query.filter_by(session_id=session_id).all(), "global_id")
                replace_global(MtmcTrackEvent.query.filter_by(session_id=session_id).all(), "global_id")
                replace_global(MtmcAssociationEdge.query.filter_by(session_id=session_id).all(), "source_global_id", "target_global_id")
                replace_global(MtmcCrossCameraEvent.query.filter_by(session_id=session_id).all(), "global_id")
                replace_global(MtmcVehiclePass.query.filter_by(session_id=session_id).all(), "global_id")

                old_person = MtmcGlobalPerson.query.filter_by(global_id=global_id).first()
                keep_person = MtmcGlobalPerson.query.filter_by(global_id=candidate_global_id).first()
                if old_person is not None:
                    if keep_person is None:
                        old_person.global_id = candidate_global_id
                    else:
                        for field in ("reid_person_id", "face_person_id", "display_name"):
                            if not getattr(keep_person, field) and getattr(old_person, field):
                                setattr(keep_person, field, getattr(old_person, field))
                        db.session.delete(old_person)

                old_vehicle = MtmcGlobalVehicle.query.filter_by(global_id=global_id).first()
                keep_vehicle = MtmcGlobalVehicle.query.filter_by(global_id=candidate_global_id).first()
                if old_vehicle is not None:
                    if keep_vehicle is None:
                        old_vehicle.global_id = candidate_global_id
                    else:
                        for field in ("plate", "visual_key", "identity_key"):
                            if not getattr(keep_vehicle, field) and getattr(old_vehicle, field):
                                setattr(keep_vehicle, field, getattr(old_vehicle, field))
                        db.session.delete(old_vehicle)
            db.session.commit()
            return True
    except Exception as e:  # noqa: BLE001
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        log.debug("resolve candidate pair failed: %s", e)
        return False
