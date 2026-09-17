"""Thread-safe local and managed-camera squat sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
import uuid

import cv2
import numpy as np

from services.squat_counter import SquatConfig, SquatCounter
from services.squat_video import annotate_squat_frame


class SessionError(ValueError):
    pass


@dataclass
class SquatSession:
    id: str
    owner_id: str
    source_type: str
    estimator: object
    counter: SquatCounter
    created_at: float
    last_activity: float
    status: str = "running"
    last_sequence: int = -1
    latest_jpeg: bytes | None = None
    latest_state: dict | None = None
    error: str | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    capture: object | None = None
    thread: threading.Thread | None = None

    def public_snapshot(self):
        state = dict(self.latest_state or self.counter.snapshot())
        return {
            "sessionId": self.id,
            "sourceType": self.source_type,
            "status": self.status,
            "error": self.error,
            **state,
        }


class SquatSessionManager:
    def __init__(
        self,
        *,
        max_sessions_per_owner=2,
        idle_seconds=60.0,
        max_frame_bytes=2 * 1024 * 1024,
        clock=time.monotonic,
    ):
        self.max_sessions_per_owner = int(max_sessions_per_owner)
        self.idle_seconds = float(idle_seconds)
        self.max_frame_bytes = int(max_frame_bytes)
        self.clock = clock
        self._sessions: dict[str, SquatSession] = {}
        self._lock = threading.RLock()

    def _active_count(self, owner_id):
        return sum(
            session.owner_id == owner_id and session.status == "running"
            for session in self._sessions.values()
        )

    def _create(self, owner_id, source_type, estimator, config):
        owner_id = str(owner_id)
        with self._lock:
            if self._active_count(owner_id) >= self.max_sessions_per_owner:
                raise SessionError("active squat session limit reached")
            now = self.clock()
            session = SquatSession(
                id=uuid.uuid4().hex,
                owner_id=owner_id,
                source_type=source_type,
                estimator=estimator,
                counter=SquatCounter(config),
                created_at=now,
                last_activity=now,
            )
            self._sessions[session.id] = session
            return session

    def create_local(self, owner_id, estimator, config: SquatConfig):
        return self._create(owner_id, "local", estimator, config)

    def create_network(
        self,
        owner_id,
        source,
        estimator,
        config: SquatConfig,
        *,
        capture_factory=cv2.VideoCapture,
        max_reconnects=3,
    ):
        session = self._create(owner_id, "network", estimator, config)
        session.thread = threading.Thread(
            target=self._network_loop,
            args=(session, source, capture_factory, int(max_reconnects)),
            daemon=True,
        )
        session.thread.start()
        return session

    def _lookup(self, session_id, owner_id):
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.owner_id != str(owner_id):
                raise SessionError("squat session not found")
            return session

    def submit_frame(self, session_id, owner_id, sequence, captured_at, jpeg):
        session = self._lookup(session_id, owner_id)
        if session.source_type != "local" or session.status != "running":
            raise SessionError("local squat session is not running")
        if len(jpeg) > self.max_frame_bytes:
            raise SessionError("frame exceeds size limit")
        sequence = int(sequence)
        if sequence <= session.last_sequence:
            raise SessionError("frame sequence must be strictly increasing")
        data = np.frombuffer(jpeg, dtype=np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            raise SessionError("invalid JPEG frame")
        state = session.counter.update(session.estimator.infer(frame), float(captured_at))
        annotated = annotate_squat_frame(frame, state)
        ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise SessionError("failed to encode annotated frame")
        session.last_sequence = sequence
        session.last_activity = self.clock()
        session.latest_state = state
        session.latest_jpeg = encoded.tobytes()
        return {
            "frameSequence": sequence,
            "state": dict(state),
            "annotatedJpeg": session.latest_jpeg,
        }

    def snapshot(self, session_id, owner_id):
        return self._lookup(session_id, owner_id).public_snapshot()

    def stop(self, session_id, owner_id, *, status="stopped"):
        session = self._lookup(session_id, owner_id)
        if session.status == "running":
            session.status = status
            session.stop_event.set()
            capture = session.capture
            if capture is not None:
                try:
                    capture.release()
                except Exception:  # noqa: BLE001 - third-party capture cleanup
                    pass
            with session.condition:
                session.condition.notify_all()
        return session.public_snapshot()

    def reap_idle(self):
        now = self.clock()
        expired = []
        with self._lock:
            candidates = list(self._sessions.values())
        for session in candidates:
            if session.status == "running" and now - session.last_activity > self.idle_seconds:
                self.stop(session.id, session.owner_id, status="expired")
                expired.append(session.id)
        return expired

    def _network_loop(self, session, source, capture_factory, max_reconnects):
        failures = 0
        started = self.clock()
        while not session.stop_event.is_set() and failures <= max_reconnects:
            capture = capture_factory(source)
            session.capture = capture
            try:
                if not capture.isOpened():
                    failures += 1
                    continue
                while not session.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        failures += 1
                        break
                    timestamp = max(0.0, self.clock() - started)
                    state = session.counter.update(session.estimator.infer(frame), timestamp)
                    annotated = annotate_squat_frame(frame, state)
                    encoded_ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
                    if not encoded_ok:
                        continue
                    session.latest_state = state
                    session.latest_jpeg = encoded.tobytes()
                    session.last_activity = self.clock()
                    failures = 0
                    with session.condition:
                        session.condition.notify_all()
            except Exception as exc:  # noqa: BLE001 - background source failure
                failures += 1
                session.error = str(exc)
            finally:
                try:
                    capture.release()
                except Exception:  # noqa: BLE001
                    pass
                session.capture = None
        if not session.stop_event.is_set():
            session.status = "error"
            session.error = session.error or "network camera disconnected"
            with session.condition:
                session.condition.notify_all()

    def mjpeg(self, session_id, owner_id):
        session = self._lookup(session_id, owner_id)
        if session.source_type != "network":
            raise SessionError("MJPEG stream is only available for network sessions")
        last_frame = None
        while session.status == "running" or session.latest_jpeg is not None:
            with session.condition:
                if session.latest_jpeg is last_frame and session.status == "running":
                    session.condition.wait(timeout=1.0)
                frame = session.latest_jpeg
            if frame is None or frame is last_frame:
                if session.status != "running":
                    break
                continue
            last_frame = frame
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            if session.status != "running":
                break
