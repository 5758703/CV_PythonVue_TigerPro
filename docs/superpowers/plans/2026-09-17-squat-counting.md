# 健身蹲起计数实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在生产模型场景中提供基于既有姿态模型的单主训练者蹲起计数，支持上传视频、本地摄像头和已登记网络摄像头。

**Architecture:** 新建纯几何/状态机服务作为核心，并由视频任务和实时会话两个适配层调用。上传视频写出标注 MP4；本地摄像头逐帧上传；网络摄像头由后端拉流并输出 MJPEG。前端使用独立工作台管理三类来源和资源生命周期。

**Tech Stack:** Python 3、Flask、OpenCV、Ultralytics/rtmlib、pytest、Vue 3、Axios、Node test runner、Vite

**Spec:** `docs/superpowers/specs/2026-09-17-squat-counting-design.md`

## Global Constraints

- 只统计一个主训练者，不进行多人独立计数。
- 完整经过“站立 → 下蹲到底 → 重新站立”才计数一次。
- 默认站立阈值为 `160°`，下蹲阈值为 `100°`，状态确认需要连续 3 个有效采样，目标丢失宽限为 1 秒。
- 上传视频生成标注 MP4；本地和网络摄像头只保留会话摘要，不录制。
- 网络源只能来自用户有权访问且已启用的 `Camera` 记录，不能接受任意 RTSP URL。
- 所有新增生产函数先有失败测试，再写最小实现。

---

### Task 1: 纯蹲起几何与状态机

**Files:**
- Create: `backend/services/squat_counter.py`
- Create: `backend/unittests/test_squat_counter.py`

**Interfaces:**
- Produces: `SquatConfig`, `SquatCounter.update(persons: list[dict], timestamp: float) -> dict`, `SquatCounter.snapshot() -> dict`, `knee_angle(hip, knee, ankle) -> float | None`
- Person input uses existing normalized pose dictionaries containing `bbox`, `score`, and COCO-17 `keypoints` entries shaped as `[x, y, confidence]`.

- [ ] **Step 1: Write failing geometry and leg-selection tests**

```python
def test_knee_angle_is_ninety_degrees():
    assert knee_angle((0, 0), (0, 1), (1, 1)) == pytest.approx(90.0)

def test_counter_uses_only_confident_leg():
    result = SquatCounter().update([person(left_angle=170, right_angle=80, right_conf=0.05)], 0.0)
    assert result["kneeAngle"] == pytest.approx(170.0)
```

- [ ] **Step 2: Run tests and verify the imports/functions fail**

Run: `python -m pytest backend/unittests/test_squat_counter.py -q`

Expected: FAIL because `services.squat_counter` does not exist.

- [ ] **Step 3: Implement immutable configuration and pure geometry helpers**

```python
@dataclass(frozen=True)
class SquatConfig:
    keypoint_conf: float = 0.25
    standing_angle: float = 160.0
    bottom_angle: float = 100.0
    confirm_frames: int = 3
    lost_grace_seconds: float = 1.0
    smoothing_window: int = 5

def knee_angle(hip, knee, ankle): ...
def leg_angle(person, config): ...
def select_primary_person(persons, previous_bbox, config): ...
```

- [ ] **Step 4: Run geometry tests and verify they pass**

Run: `python -m pytest backend/unittests/test_squat_counter.py -q`

Expected: geometry and leg-selection cases PASS.

- [ ] **Step 5: Add failing state-machine tests**

Cover a complete repetition, half squat, initial bottom pose, threshold jitter, two repetitions, a distractor person, brief loss recovery, and loss beyond one second cancelling the partial repetition.

```python
def test_complete_stand_bottom_stand_cycle_counts_once():
    counter = SquatCounter(SquatConfig(confirm_frames=2, smoothing_window=1))
    feed_angles(counter, [170, 170, 130, 95, 95, 125, 165, 165])
    assert counter.snapshot()["count"] == 1
    assert counter.snapshot()["stage"] == "standing"
```

- [ ] **Step 6: Run state-machine tests and verify expected count failures**

Run: `python -m pytest backend/unittests/test_squat_counter.py -q`

Expected: FAIL because `SquatCounter` does not yet implement the lifecycle.

- [ ] **Step 7: Implement target continuity, smoothing, stages, loss handling, and summary metrics**

Return camelCase fields used by the API: `count`, `stage`, `kneeAngle`, `rawKneeAngle`, `trackingStatus`, `activeSeconds`, `minKneeAngle`, `averageKneeAngle`, `completedRep`, `primaryPerson`.

- [ ] **Step 8: Run the core test file**

Run: `python -m pytest backend/unittests/test_squat_counter.py -q`

Expected: PASS.

- [ ] **Step 9: Commit the core**

```bash
git add backend/services/squat_counter.py backend/unittests/test_squat_counter.py
git commit -m "feat: add squat counting state machine"
```

### Task 2: 姿态运行时适配、标注和上传视频任务

**Files:**
- Create: `backend/services/squat_video.py`
- Create: `backend/unittests/test_squat_video.py`
- Modify: `backend/services/squat_counter.py`

**Interfaces:**
- Consumes: `SquatCounter.update(...)`, existing pose runtimes selected by model `library` and `model_key`.
- Produces: `PoseFrameEstimator.infer(frame) -> list[dict]`, `annotate_squat_frame(frame, state) -> ndarray`, `process_squat_video(estimator, src_path, dst_path, config, progress_cb=None) -> dict`.

- [ ] **Step 1: Write failing estimator-normalization and video-summary tests**

Use a fake estimator returning deterministic COCO-17 persons and a short temporary OpenCV video. Assert output frame count, count, rep timestamps, FPS fields, and progress reaching 100.

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest backend/unittests/test_squat_video.py -q`

Expected: FAIL because `services.squat_video` does not exist.

- [ ] **Step 3: Implement the runtime adapter and video loop**

```python
def process_squat_video(estimator, src_path, dst_path, config, progress_cb=None):
    counter = SquatCounter(config)
    # Open capture/writer, infer each frame, update counter, annotate, report progress.
    # Release both handles in finally and return the frozen summary.
```

Reuse the same Ultralytics, YOLO-Master, and rtmlib resolution rules already used by `routes.ai_model._resolve_pose_runtime`; do not duplicate model-path security checks.

- [ ] **Step 4: Run focused tests and all existing pose/fall tests**

Run: `python -m pytest backend/unittests/test_squat_video.py backend/unittests/test_fall_video.py backend/unittests/test_model_scenario_inference.py -q`

Expected: PASS.

- [ ] **Step 5: Commit video processing**

```bash
git add backend/services/squat_video.py backend/services/squat_counter.py backend/unittests/test_squat_video.py
git commit -m "feat: process squat counting videos"
```

### Task 3: 上传视频 API 与安全输出

**Files:**
- Create: `backend/routes/squat.py`
- Modify: `backend/routes/__init__.py`
- Create: `backend/unittests/test_squat_api.py`

**Interfaces:**
- Consumes: `process_squat_video`, `AiModel`, `_resolve_pose_runtime`.
- Produces: `/api/ai/squat/video`, `/video-progress/<job_id>`, `/output/<name>`.

- [ ] **Step 1: Write failing Flask API tests**

Test missing/invalid file, non-pose model, invalid threshold ordering, task creation, owner isolation, progress completion/failure, rejected arbitrary output names, and successful MP4 download.

```python
response = client.post("/api/ai/squat/video", data={
    "file": (io.BytesIO(video_bytes), "squats.mp4"),
    "modelId": str(model.id),
    "standingAngle": "160",
    "bottomAngle": "100",
}, headers=headers)
assert response.status_code == 200
assert response.json["data"]["jobId"]
```

- [ ] **Step 2: Run and verify the blueprint/routes are missing**

Run: `python -m pytest backend/unittests/test_squat_api.py -q`

Expected: FAIL/404.

- [ ] **Step 3: Implement validated job endpoints and register the blueprint**

Use `secure_filename`, UUID job IDs, a lock-protected in-memory job registry keyed by creator identity, configured upload/output directories, and a daemon worker. Validate `bottomAngle < standingAngle`, angle range, confirm frames, video extension/size, enabled pose model, and output filename suffix.

- [ ] **Step 4: Run API and blueprint regression tests**

Run: `python -m pytest backend/unittests/test_squat_api.py backend/unittests/test_model_scenario_api.py backend/unittests/test_openapi_catalog.py -q`

Expected: PASS.

- [ ] **Step 5: Commit upload API**

```bash
git add backend/routes/squat.py backend/routes/__init__.py backend/unittests/test_squat_api.py
git commit -m "feat: expose squat video analysis API"
```

### Task 4: 本地与网络摄像头实时会话

**Files:**
- Create: `backend/services/squat_sessions.py`
- Modify: `backend/routes/squat.py`
- Create: `backend/unittests/test_squat_sessions.py`
- Modify: `backend/unittests/test_squat_api.py`

**Interfaces:**
- Produces: `SquatSessionManager.create_local(...)`, `create_network(...)`, `submit_frame(...)`, `snapshot(...)`, `mjpeg(...)`, `stop(...)`, `reap_idle(...)`.
- Routes: `POST /sessions`, `POST /sessions/<id>/frames`, `GET /sessions/<id>`, `GET /sessions/<id>/stream`, `DELETE /sessions/<id>`.

- [ ] **Step 1: Write failing session-manager unit tests**

Cover ordered frame acceptance, duplicate/out-of-order rejection, owner isolation, idempotent stop, active-session limit, idle expiry, JPEG limits, network capture reconnect limit, frozen state during outage, and capture/thread release.

- [ ] **Step 2: Run and verify failure**

Run: `python -m pytest backend/unittests/test_squat_sessions.py -q`

Expected: FAIL because the manager is missing.

- [ ] **Step 3: Implement thread-safe session objects and manager**

Local sessions run inference synchronously per accepted frame. Network sessions own a daemon capture loop and latest annotated JPEG guarded by a condition variable. Store only bounded state and the latest frame; never store live-session video.

- [ ] **Step 4: Add failing route tests for all five session endpoints**

Assert network sessions resolve an enabled `Camera` row, local sessions reject `cameraId`, arbitrary URLs are ignored/rejected, MJPEG is network-only, and delete releases resources.

- [ ] **Step 5: Implement endpoints and query-token support for the MJPEG `<img>` request**

Follow the project camera-stream authentication pattern for `jwt` query tokens while retaining normal JWT headers for JSON and frame endpoints.

- [ ] **Step 6: Run all squat backend tests**

Run: `python -m pytest backend/unittests/test_squat_counter.py backend/unittests/test_squat_video.py backend/unittests/test_squat_sessions.py backend/unittests/test_squat_api.py -q`

Expected: PASS.

- [ ] **Step 7: Commit real-time sessions**

```bash
git add backend/services/squat_sessions.py backend/routes/squat.py backend/unittests/test_squat_sessions.py backend/unittests/test_squat_api.py
git commit -m "feat: add live squat counting sessions"
```

### Task 5: 注册生产场景及前端状态/API 契约

**Files:**
- Modify: `backend/services/model_scenarios.py`
- Modify: `backend/unittests/test_model_scenarios.py`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/scenarioState.js`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`
- Create: `frontend/frontend_admin/src/api/squat.js`

**Interfaces:**
- Produces: `squat-counting` group, `squat_counting` workbench resolution, API client methods `startVideo`, `videoProgress`, `createSession`, `submitFrame`, `session`, `stopSession`, `streamUrl`, `outputUrl`.

- [ ] **Step 1: Add failing catalog tests**

Assert the new group is published, uses `squat_counting`, includes only supported pose model keys, advertises video/local/network input modes, and resolves legacy model selection normally.

- [ ] **Step 2: Run backend catalog tests and verify failure**

Run: `python -m pytest backend/unittests/test_model_scenarios.py -q`

Expected: FAIL because the group is absent.

- [ ] **Step 3: Register the group and shared models**

Add the group after body pose with project copy, workflow, outputs, metrics, risks, defaults, and input policy matching the design. Do not duplicate model manifests.

- [ ] **Step 4: Add failing frontend state tests**

```javascript
assert.equal(resolveWorkbench('squat_counting'), 'squat_counting')
assert.deepEqual(validateSquatParameters({ standingAngle: 100, bottomAngle: 160 }), [
  '站立阈值必须大于下蹲阈值',
])
```

Also test accepted video candidates, parameter serialization, session response normalization, and source-switch cleanup state.

- [ ] **Step 5: Run Node tests and verify failure**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

Expected: FAIL for missing squat helpers.

- [ ] **Step 6: Implement pure state helpers and API client**

Keep browser APIs out of `scenarioState.js`; export pure validation/normalization helpers so Node tests remain deterministic. Build authenticated stream/output URLs using the existing user-store/token convention.

- [ ] **Step 7: Run catalog and frontend state tests**

Run: `python -m pytest backend/unittests/test_model_scenarios.py -q`

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

Expected: PASS.

- [ ] **Step 8: Commit catalog and contracts**

```bash
git add backend/services/model_scenarios.py backend/unittests/test_model_scenarios.py frontend/frontend_admin/src/views/ai/scenarios/scenarioState.js frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs frontend/frontend_admin/src/api/squat.js
git commit -m "feat: register squat counting scenario"
```

### Task 6: 专用蹲起工作台

**Files:**
- Create: `frontend/frontend_admin/src/views/ai/scenarios/workbenches/SquatCountingWorkbench.vue`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/ScenarioApp.vue`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/scenarios.css`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

**Interfaces:**
- Consumes: `squatApi`, camera listing API, pure helpers from `scenarioState.js`, selected scenario/model props.
- Produces: `completed` event with `modelKey` and final summary.

- [ ] **Step 1: Add failing mapping/lifecycle state tests**

Test `squat_counting` mapping, default thresholds, source-specific run eligibility, stale async response rejection, and cleanup decisions for file/local/network transitions.

- [ ] **Step 2: Run tests and verify failure**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

Expected: FAIL for missing workbench behavior.

- [ ] **Step 3: Implement the three-source workbench**

The component must:

- upload and poll video jobs, then expose playback/download;
- start `getUserMedia`, draw bounded-size JPEG frames to a canvas, submit one in-flight request at a time, and discard stale responses;
- list enabled managed cameras, create a network session, display its MJPEG URL, and poll status;
- show count, stage, knee angle, tracking status, active time, FPS, progress, errors, and final summary;
- stop all timers, media tracks, object URLs, pending request generations, and server sessions on source/model change and `onBeforeUnmount`.

- [ ] **Step 4: Register and style the workbench**

Import `SquatCountingWorkbench` in `ScenarioApp.vue`, map `squat_counting`, add its ability label, and add responsive styles reusing existing scenario tokens/classes.

- [ ] **Step 5: Run state tests and production build**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

Run: `npm run build` in `frontend/frontend_admin`

Expected: PASS with no Vue compile errors.

- [ ] **Step 6: Commit the workbench**

```bash
git add frontend/frontend_admin/src/views/ai/scenarios/workbenches/SquatCountingWorkbench.vue frontend/frontend_admin/src/views/ai/scenarios/ScenarioApp.vue frontend/frontend_admin/src/views/ai/scenarios/scenarios.css frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs
git commit -m "feat: add squat counting workbench"
```

### Task 7: 全链路回归、文档和收尾

**Files:**
- Modify: `backend/docs/model_scenario_manifests.md`
- Modify: `CHANGELOG.md`
- Modify: only files required by failures attributable to this feature

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified production scenario and operator-facing documentation.

- [ ] **Step 1: Document the scene and operational limits**

Document model reuse, endpoints, default thresholds, single-person rule, input limits, real-time non-recording behavior, and network-camera registration requirement.

- [ ] **Step 2: Run the complete relevant backend suite**

Run: `python -m pytest backend/unittests/test_squat_counter.py backend/unittests/test_squat_video.py backend/unittests/test_squat_sessions.py backend/unittests/test_squat_api.py backend/unittests/test_model_scenarios.py backend/unittests/test_model_scenario_api.py backend/unittests/test_model_scenario_inference.py backend/unittests/test_openapi_model_scenarios.py backend/unittests/test_camera_motion.py -q`

Expected: PASS.

- [ ] **Step 3: Run frontend state tests and build**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

Run: `npm run build` in `frontend/frontend_admin`

Expected: PASS.

- [ ] **Step 4: Inspect diffs and repository state**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors and only intentional files changed.

- [ ] **Step 5: Commit final documentation/fixes**

```bash
git add backend/docs/model_scenario_manifests.md CHANGELOG.md
git commit -m "docs: document squat counting workflow"
```

