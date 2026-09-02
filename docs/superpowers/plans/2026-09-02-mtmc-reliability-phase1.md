# MTMC Reliability Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate MTMC Global-ID reuse and oscillation, stabilize static targets, and make non-overlap handoffs obey directed topology using correct multi-frame ReID evidence.

**Architecture:** Preserve the existing detector, local trackers, TrackletBuilder, MtmcAssociator and HTTP API boundaries. Correct model-space handling and lifecycle semantics first, then make topology/final scoring authoritative, introduce per-camera Global state and atomic evidence, and expose the resulting runtime state in the existing workbench.

**Tech Stack:** Python 3, Flask, SQLAlchemy, NumPy, OpenCV, ONNX Runtime, FAISS (optional), pytest, Vue 3, Element Plus, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-02-mtmc-reliability-upgrade-design.md`

## Global Constraints

- Work directly on the user-authorized `main` branch; do not create a worktree.
- Preserve existing MTMC routes, response fields, persistence tables and monitoring-wall URLs unless this plan explicitly adds fields.
- Do not add a new training framework or mandatory GPU dependency in Phase 1.
- Missing strong ReID, vehicle ReID, topology or timestamps must never degrade silently.
- Non-overlap camera pairs without an explicit directed edge are unreachable by default.
- Different embedding model spaces must never be padded, trimmed, averaged or compared with each other.
- Uncertain matches become `candidate` or `new`; threshold reduction alone is not an accepted fix.
- Every task uses red-green-refactor TDD, one implementation agent, one independent reviewer, and an isolated commit.

---

### Task 1: Correct ReID Input Shapes and Isolate Model Spaces

**Files:**
- Modify: `backend/services/strong_reid.py`
- Modify: `backend/services/reid_gallery.py`
- Modify: `backend/services/mtmc_engine.py`
- Test: `backend/unittests/test_mtmc_reid_runtime.py`

**Interfaces:**
- Produces: `extract_person_embeddings(...) -> dict[str, np.ndarray]`, keyed by stable model-space key.
- Produces: `fuse_similarity_scores(scores, weights) -> float | None` for score-level fusion only.
- Preserves: `extract_person_embedding(...)` as a compatibility wrapper returning the best single available space.
- Consumes: ONNX input metadata and Gallery rows carrying their existing `model_key`.

- [ ] **Step 1: Write failing tests** proving OSNet and CLIP `[N,3,256,128]` retain their declared dimensions, two unrelated embedding spaces are never element-wise combined, Gallery comparison uses matching model keys, and partial backend failure renormalizes remaining score weights.

```python
def test_declared_onnx_spatial_shape_is_used(fake_session):
    fake_session.input_shape = [1, 3, 256, 128]
    assert resolve_input_spatial(fake_session) == (128, 256)

def test_score_fusion_renormalizes_available_backends():
    assert fuse_similarity_scores({"youtu": 0.8}, {"strong": 0.65, "youtu": 0.35}) == pytest.approx(0.8)

def test_embedding_spaces_are_returned_separately(monkeypatch):
    result, _ = extract_person_embeddings(np.zeros((256, 128, 3), np.uint8), youtu_root="y", strong_root="s")
    assert set(result) == {"strong", "youtu"}
```

- [ ] **Step 2: Run `pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider` and verify the new tests fail for missing APIs or the current 224×224 behavior.**

- [ ] **Step 3: Implement exact input-shape parsing, separate model-space outputs, matching-space Gallery lookup, score-level fusion, and structured readiness/error metadata.** Do not concatenate or pad embeddings across models.

- [ ] **Step 4: Run the focused test plus `pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider`; all must pass.**

- [ ] **Step 5: Commit with `git commit -m "fix: correct MTMC ReID model spaces"`.**

---

### Task 2: Stabilize Tracklet Lifecycle and Multi-Keyframe Scheduling

**Files:**
- Modify: `backend/services/mtmc_local_track.py`
- Modify: `backend/services/mtmc_tracklet.py`
- Modify: `backend/services/mtmc_engine.py`
- Test: `backend/unittests/test_mtmc_tracklet_lifecycle.py`

**Interfaces:**
- Produces: tracker removal information without changing existing `update(...) -> list[Tracklet]` callers, via `pop_removed_track_ids() -> set[int]` on every tracker implementation.
- Produces: `TrackletBuilder.should_sample_embedding(now, quality, view_token=None) -> bool`.
- Produces: independent `person_reid_budget` and `vehicle_reid_budget` scheduling in the frame processor.

- [ ] **Step 1: Write failing tests** for a static target surviving temporary empty detections, builder finalization only after tracker removal/timeout, at least three spaced quality keyframes, and vehicle budget remaining available in a crowded person frame.

```python
def test_tracklet_survives_single_frame_detector_miss(session, cam_state):
    process_tracks(session, cam_state, tracks=[static_vehicle(7)], now=10.0)
    process_tracks(session, cam_state, tracks=[], now=10.25)
    assert 7 in cam_state.vehicle_builders

def test_keyframe_sampler_collects_quality_improvements():
    b = make_builder("vehicle")
    assert b.should_sample_embedding(1.0, 0.2)
    assert not b.should_sample_embedding(1.1, 0.2)
    assert b.should_sample_embedding(2.0, 0.5)
```

- [ ] **Step 2: Run `pytest backend/unittests/test_mtmc_tracklet_lifecycle.py -q -p no:cacheprovider` and verify failures reproduce premature finalization and single-frame sampling.**

- [ ] **Step 3: Add explicit tracker removal/grace semantics, preserve builders during short misses, add quality/time keyframe scheduling, and split person/vehicle budgets.** Prioritize unsampled new tracks, tracks near removal, candidates, and quality improvements in that order.

- [ ] **Step 4: Run focused tests plus `pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider`; all must pass.**

- [ ] **Step 5: Commit with `git commit -m "fix: stabilize MTMC tracklet lifecycle"`.**

---

### Task 3: Make Directed Topology and Final Scores Authoritative

**Files:**
- Modify: `backend/services/mtmc_associator.py`
- Modify: `backend/services/mtmc_engine.py`
- Modify: `backend/services/pipeline_mtmc.py`
- Modify: `backend/routes/mtmc.py`
- Test: `backend/unittests/test_mtmc_topology_policy.py`

**Interfaces:**
- Produces: immutable `TopologyRule(min_sec: float, max_sec: float, weight: float, edge_type: str)`.
- Produces: `_score_long_term(...)` whose `final` includes appearance, topology weight, time likelihood, recency and applicable identity evidence.
- Preserves: existing topology CRUD JSON fields; accepts optional `edgeType` with `non_overlap` default for persisted edges.

- [ ] **Step 1: Write failing tests** proving A→B does not imply B→A, missing non-overlap edges reject, `time_w` and configured weight change final score, raw ReID cannot bypass a low final score, overlap edges accept `dt=0`, and pipeline sessions receive database topology.

```python
def test_topology_is_directed():
    assoc = MtmcAssociator(appear_thresh=0.4)
    assoc.set_topology([{"fromCameraId": 1, "toCameraId": 2, "minTransitSec": 5, "maxTransitSec": 20}])
    assert assoc._topology_ok(1, 2, 10) > 0
    assert assoc._topology_ok(2, 1, 10) == 0

def test_raw_reid_cannot_bypass_final_threshold():
    result = associate_across_unreachable_pair(reid_score=0.99)
    assert result.last_assoc_mode == "new"
```

- [ ] **Step 2: Run `pytest backend/unittests/test_mtmc_topology_policy.py -q -p no:cacheprovider` and verify failures show the current symmetric/soft topology behavior.**

- [ ] **Step 3: Preserve direction, reject missing edges, multiply time and weight into final, tier on final, distinguish overlap edges, and load the same topology through API and pipeline entry points.**

- [ ] **Step 4: Run focused tests plus `pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_p2.py -q -p no:cacheprovider`; all must pass.**

- [ ] **Step 5: Commit with `git commit -m "fix: enforce directed MTMC topology"`.**

---

### Task 4: Prevent Global-ID Reuse and Prototype Pollution

**Files:**
- Modify: `backend/services/mtmc_associator.py`
- Modify: `backend/services/mtmc_active_gallery.py`
- Modify: `backend/services/mtmc_engine.py`
- Test: `backend/unittests/test_mtmc_global_stability.py`

**Interfaces:**
- Produces: per-camera Global observation state containing active/lost interval and last observation timestamp.
- Produces: best/second-best candidate scoring and configurable minimum margin.
- Produces: prototype update policy accepting only confirmed, quality-qualified observations.
- Preserves: `GlobalTrack.camera_id` and `last_seen` as compatibility summaries.

- [ ] **Step 1: Write failing tests** for two static vehicles never exchanging IDs, local-ID reconstruction recovering the original same-camera Global, a later similar vehicle not stealing an occupied/physically invalid Global, overlapping cameras remaining simultaneously active, low-margin matches becoming candidate, and candidates not modifying confirmed prototypes.

```python
def test_two_static_vehicles_never_exchange_globals():
    first = run_static_pair(frames=20)
    assert all(frame["left"] == first[0]["left"] for frame in first)
    assert all(frame["right"] == first[0]["right"] for frame in first)

def test_candidate_does_not_update_confirmed_prototype():
    before = gallery.prototype("vehicle", "V1", camera_id=1).copy()
    associate_ambiguous_candidate("V1")
    np.testing.assert_allclose(gallery.prototype("vehicle", "V1", camera_id=1), before)
```

- [ ] **Step 2: Run `pytest backend/unittests/test_mtmc_global_stability.py -q -p no:cacheprovider` and verify current single-camera-state, no-margin or prototype-update behavior fails.**

- [ ] **Step 3: Add per-camera state, occupied-Global guards, same-camera recovery, best-vs-second margin, mutual-best gating where a batch exists, and quality/decision-aware prototype updates.**

- [ ] **Step 4: Run focused tests plus all existing MTMC unit tests; all must pass.**

- [ ] **Step 5: Commit with `git commit -m "fix: protect MTMC global identity stability"`.**

---

### Task 5: Make Vehicle Evidence, Association Evidence, and Stop Semantics Correct

**Files:**
- Modify: `backend/services/vehicle_reid_feat.py`
- Modify: `backend/services/mtmc_associator.py`
- Modify: `backend/services/mtmc_engine.py`
- Modify: `backend/services/mtmc_persist.py`
- Test: `backend/unittests/test_mtmc_evidence_consistency.py`

**Interfaces:**
- Produces: `associate_with_evidence(...) -> AssociationResult(global_track, evidence)`; existing `associate(...) -> GlobalTrack` delegates to it for compatibility, while the engine uses the atomic API.
- Produces: vehicle visual score computed against a candidate prototype, never self-similarity.
- Produces: multi-observation normalized plate vote.
- Produces: `stop_session(...)` that joins workers and finalizes builders before upload cleanup.

- [ ] **Step 1: Write failing tests** for non-constant vehicle visual scores, character-normalized multi-frame plate voting, concurrent associations retaining their own evidence, stop finalization, cleanup order, and candidate promotion updating all related persisted rows.

```python
def test_vehicle_visual_score_is_candidate_similarity():
    assert vehicle_candidate_score(unit_x(), unit_y()) == pytest.approx(0.0)

def test_association_evidence_is_call_local():
    a, b = run_two_thread_associations()
    assert a.evidence.target_global_id == a.global_track.global_id
    assert b.evidence.target_global_id == b.global_track.global_id
```

- [ ] **Step 2: Run `pytest backend/unittests/test_mtmc_evidence_consistency.py -q -p no:cacheprovider` and verify the current self-score/shared evidence/stop behavior fails.**

- [ ] **Step 3: Return evidence atomically, correct vehicle candidate scoring and plate aggregation, join/finalize before cleanup, and perform transactionally consistent candidate promotion/rejection.** Keep compatibility accessors only where existing callers require them.

- [ ] **Step 4: Run focused tests plus `pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_p2.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider`; all must pass.**

- [ ] **Step 5: Commit with `git commit -m "fix: make MTMC evidence lifecycle consistent"`.**

---

### Task 6: Expose Runtime Truth and Add Field-Problem Regression Coverage

**Files:**
- Modify: `backend/services/mtmc_engine.py`
- Modify: `backend/routes/mtmc.py`
- Modify: `frontend/frontend_admin/src/views/ai/mtmc/index.vue`
- Create: `frontend/frontend_admin/src/utils/mtmcRuntimeStatus.js`
- Create: `frontend/frontend_admin/src/utils/mtmcRuntimeStatus.test.js`
- Test: `backend/unittests/test_mtmc_runtime_status.py`
- Test: `backend/unittests/test_mtmc_stream_regressions.py`

**Interfaces:**
- Produces session `runtime` fields for selected model key/version, backend readiness, provider, input size, embedding dimension, degradation reason, budget/queue counters and effective thresholds.
- Produces association evidence fields `appearanceScore`, `topologyScore`, `timeScore`, `margin`, `finalScore` without changing legacy fields.
- Produces frontend pure helpers for status labels and risk presentation.

- [ ] **Step 1: Write failing backend and frontend tests** for actual model/degraded reporting, distinct event-vs-association scores, effective directed topology display, and the four field regressions: wrong reuse, static-ID switching, failed non-overlap continuation, delayed oscillation.

```javascript
test('degraded strong ReID is visible and never labeled ready', () => {
  assert.equal(runtimeTone({ ready: false, degradedReason: 'shape mismatch' }), 'danger')
})
```

```python
def test_stream_regression_static_vehicle_keeps_global_id():
    ids = replay_fixture("static_vehicle_short_misses")
    assert len(set(ids)) == 1
```

- [ ] **Step 2: Run `pytest backend/unittests/test_mtmc_runtime_status.py backend/unittests/test_mtmc_stream_regressions.py -q -p no:cacheprovider` and `node --test src/utils/mtmcRuntimeStatus.test.js`; verify failures.**

- [ ] **Step 3: Add runtime snapshot fields and counters, display actual models/degradation/effective policy and score breakdown in the existing MTMC workbench, and add deterministic synthetic replay fixtures for all four reported field failures.** Keep advanced controls grouped and default to the recommended model selected by the backend.

- [ ] **Step 4: Run all MTMC backend tests, frontend utility tests, and `npm run build`; all must pass.**

- [ ] **Step 5: Commit with `git commit -m "feat: expose MTMC runtime reliability"`.**

---

## Phase 1 Final Verification

- [ ] Run `pytest backend/unittests/test_mtmc*.py -q -p no:cacheprovider`.
- [ ] Run `node --test src/utils/mtmcRuntimeStatus.test.js` in `frontend/frontend_admin`.
- [ ] Run `npm run build` in `frontend/frontend_admin`.
- [ ] Run `git diff --check` and confirm a clean worktree.
- [ ] Dispatch a fresh whole-phase reviewer against the Phase 1 base commit and resolve all Critical/Important findings.
- [ ] Record actual test counts, build result, reviewer verdict, commits, degraded hardware/model caveats, and every controller ruling in the final handoff.
