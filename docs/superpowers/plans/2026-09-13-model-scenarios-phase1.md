# Model Scenarios Phase One Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver nine independently routed production model application pages plus authenticated management and Open API endpoints for phase-one model scenarios.

**Architecture:** A backend scenario registry is the source of truth for business metadata and dynamically joins `AiModel` readiness. A narrow inference dispatcher validates each scenario and delegates to existing segmentation, detection, OBB, and ReID implementations. The Vue application maps each independent route to a shared shell and one of four focused workbenches.

**Tech Stack:** Python 3, Flask, Flask-SQLAlchemy, pytest, Vue 3 Composition API, Vue Router, Element Plus, Axios, Vite.

**Spec:** `docs/superpowers/specs/2026-09-13-model-scenarios-phase1-design.md`

## Global Constraints

- Preserve all existing routes and uncommitted user changes.
- Do not download missing model weights; report readiness truthfully.
- Never accept a model path or runtime library from the client.
- Every model gets an independent `/ai/scenarios/<model-key>` route.
- Management responses use `{code, message, data}`; Open API responses use existing `open_ok` / `open_error` envelopes.
- Uploaded files are images only in phase one and must obey the existing configured size limit and image extension allowlist.
- New behavior follows red-green-refactor; every completion claim requires a fresh full test/build run.

---

### Task 1: Phase-one scenario registry

**Files:**
- Create: `backend/services/model_scenarios.py`
- Test: `backend/unittests/test_model_scenarios.py`

**Interfaces:**
- Produces: `list_scenarios(phase: int | None = None) -> list[dict]`
- Produces: `get_scenario(model_key: str) -> dict | None`
- Produces: constants `PHASE_ONE_KEYS` and `WORKBENCH_TYPES`

- [ ] **Step 1: Write failing registry tests**

Create tests asserting exactly nine unique phase-one keys in document order; assert workbench counts `{segmentation: 2, vehicle_reid: 3, plate_detection: 3, obb_detection: 1}`; assert every item has non-empty `project`, `workflow`, `outputs`, `metrics`, `risks`, `defaults`, `input`, and `apiPath` fields; assert unknown keys return `None` and returned objects cannot mutate registry state.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/unittests/test_model_scenarios.py -q`
Expected: FAIL because `services.model_scenarios` does not exist.

- [ ] **Step 3: Implement immutable registry access**

Define nine dictionary records matching the approved spec and `MODEL_USAGE_SCENARIOS.md`. Return `copy.deepcopy` values from public functions. Set defaults per ability: segmentation `precision`/`mode` (SAM has no confidence threshold); ReID `threshold`; plate/OBB `conf/imgsz`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest backend/unittests/test_model_scenarios.py -q`
Expected: all registry tests PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/services/model_scenarios.py backend/unittests/test_model_scenarios.py && git commit -m "feat: add phase one model scenario registry"`

### Task 2: Dynamic model readiness and management catalog API

**Files:**
- Create: `backend/services/model_scenario_readiness.py`
- Create: `backend/routes/model_scenario.py`
- Modify: `backend/routes/__init__.py`
- Test: `backend/unittests/test_model_scenario_api.py`

**Interfaces:**
- Consumes: `list_scenarios`, `get_scenario`
- Produces: `scenario_with_readiness(scenario: dict) -> dict`
- Produces: blueprint at `/api/ai/model-scenarios`

- [ ] **Step 1: Write failing API tests**

Use the existing Flask `client` and authenticated headers/fixtures. Assert `GET ?phase=1` returns nine entries; detail returns the requested key; unknown key is 404; database model state is joined by `model_key`; disabled model, missing weight, and absent runtime each return explicit booleans plus `reason`; unauthenticated access is rejected.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/unittests/test_model_scenario_api.py -q`
Expected: FAIL with the route missing.

- [ ] **Step 3: Implement readiness service and blueprint**

Resolve the `AiModel` row by exact `model_key`. Compute `registered`, `weightsReady`, `runtimeReady`, `apiReady`, and `reason` without loading the model. Resolve relative weights against `MODEL_FOLDER`, require `status == "0"`, and use import discovery for the declared library. Decorate list/detail with `permission_required("ai:model:list")` / `permission_required("ai:model:query")`.

- [ ] **Step 4: Register blueprint and verify GREEN**

Run: `python -m pytest backend/unittests/test_model_scenario_api.py -q`
Expected: all management catalog tests PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/services/model_scenario_readiness.py backend/routes/model_scenario.py backend/routes/__init__.py backend/unittests/test_model_scenario_api.py && git commit -m "feat: expose model scenario catalog"`

### Task 3: Validated inference dispatcher

**Files:**
- Create: `backend/services/model_scenario_inference.py`
- Modify: `backend/routes/model_scenario.py`
- Test: `backend/unittests/test_model_scenario_inference.py`

**Interfaces:**
- Produces: `ScenarioInputError(message: str)`
- Produces: `run_scenario(model_key: str, files, form) -> dict`
- Produces: `POST /api/ai/model-scenarios/<model_key>/infer`

- [ ] **Step 1: Write failing validation/dispatch tests**

Assert missing image, invalid extension, out-of-range `conf`, invalid `imgsz`, malformed prompt JSON, mismatched ability, disabled model, and missing weights produce controlled errors. Patch only the final existing inference call and assert segmentation forwards points/labels/box, plate/OBB forwards conf/imgsz, and ReID requires `query` plus at least one `gallery` file. Assert returned data includes `modelKey`, `workbench`, `elapsedMs`, and normalized `result`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/unittests/test_model_scenario_inference.py -q`
Expected: FAIL because dispatcher is missing.

- [ ] **Step 3: Implement parsing and adapters**

Centralize image validation and numeric bounds. Resolve model exclusively by registry key. Reuse the same lower-level functions already called by `/api/ai/model/<id>/segment` and `/detect`; use existing vehicle ReID feature extraction/matching and OBB loader paths. Normalize results without inventing OCR text for detector-only models. Catch `ScenarioInputError` as 400 and sanitize unexpected failures as 500.

- [ ] **Step 4: Verify GREEN and regression subset**

Run: `python -m pytest backend/unittests/test_model_scenario_inference.py backend/unittests/test_security_open.py backend/unittests/test_mtmc_reid_runtime.py -q`
Expected: all selected tests PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/services/model_scenario_inference.py backend/routes/model_scenario.py backend/unittests/test_model_scenario_inference.py && git commit -m "feat: add scenario inference dispatcher"`

### Task 4: Dedicated Open API scenario endpoints

**Files:**
- Modify: `backend/routes/openapi_v1.py`
- Modify: `backend/openapi_spec.py`
- Test: `backend/unittests/test_openapi_model_scenarios.py`

**Interfaces:**
- Consumes: registry, readiness, `run_scenario`
- Produces: `GET /openapi/v1/model-scenarios`
- Produces: `GET /openapi/v1/model-scenarios/<model_key>`
- Produces: `POST /openapi/v1/model-scenarios/<model_key>/infer`

- [ ] **Step 1: Write failing Open API tests**

Create an OpenApp with read-only scope and prove it can list/detail but cannot infer; create infer scope and prove dispatch succeeds; assert unknown key, unavailable scenario, and malformed input use `open_error`; assert the OpenAPI JSON documents all three paths and both new scopes.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest backend/unittests/test_openapi_model_scenarios.py -q`
Expected: FAIL because endpoints/scopes are absent.

- [ ] **Step 3: Implement Open API wrappers**

Use `@require_open_scope("model-scenario:read")` and `@require_open_scope("model-scenario:infer")`. Return only public scenario metadata and readiness. Delegate inference to the same dispatcher. Use `open_ok`, `open_error`, and existing request logging/limits; do not leak absolute paths or exceptions.

- [ ] **Step 4: Update generated spec and verify GREEN**

Add request fields and representative normalized responses to `OPENAPI_SPEC`. Run: `python -m pytest backend/unittests/test_openapi_model_scenarios.py backend/unittests/test_openapi_catalog.py backend/unittests/test_security_open.py -q`
Expected: all Open API tests PASS.

- [ ] **Step 5: Commit**

Run: `git add backend/routes/openapi_v1.py backend/openapi_spec.py backend/unittests/test_openapi_model_scenarios.py && git commit -m "feat: publish model scenario Open API"`

### Task 5: Frontend scenario API and pure utilities

**Files:**
- Create: `frontend/frontend_admin/src/api/modelScenarios.js`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/scenarioState.js`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`

**Interfaces:**
- Produces: `scenarioApi.list`, `scenarioApi.get`, `scenarioApi.infer`
- Produces: `resolveWorkbench(type)`, `serializeScenarioForm(type, state)`, `downloadJson(name, value)`

- [ ] **Step 1: Write failing Node tests**

Assert all four known workbench types resolve; unknown types resolve to an unsupported state; segmentation serialization emits points/pointLabels/box; detector serialization clamps no values and preserves explicit zero for later server validation; ReID serialization uses `query` and repeated `gallery` fields.

- [ ] **Step 2: Verify RED**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`
Expected: FAIL because `scenarioState.js` is missing.

- [ ] **Step 3: Implement API and pure utilities**

Use the existing Axios wrapper. `infer` posts multipart data with `timeout: 0`. Keep browser-only download behavior behind an exported function so serialization remains directly testable in Node.

- [ ] **Step 4: Verify GREEN**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`
Expected: all utility tests PASS.

- [ ] **Step 5: Commit**

Run: `git add frontend/frontend_admin/src/api/modelScenarios.js frontend/frontend_admin/src/views/ai/scenarios/scenarioState.js frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs && git commit -m "feat: add model scenario frontend client"`

### Task 6: Scenario overview and nine independent routes

**Files:**
- Create: `frontend/frontend_admin/src/views/ai/scenarios/index.vue`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/ScenarioApp.vue`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/scenarios.css`
- Modify: `frontend/frontend_admin/src/router/index.js`

**Interfaces:**
- Consumes: `scenarioApi.list/get`, `resolveWorkbench`
- Produces: overview `/ai/scenarios` and nine explicit child routes

- [ ] **Step 1: Extend the route test first**

Add assertions to `scenarioState.test.mjs` that an exported `PHASE_ONE_ROUTE_KEYS` contains exactly the nine approved keys. Run the test and verify it FAILS because the export is absent.

- [ ] **Step 2: Add the route manifest and verify GREEN**

Export the nine keys, then add nine explicit router records whose props/meta contain a fixed `modelKey`. Do not use a public `:modelKey` route as the only implementation.

- [ ] **Step 3: Build overview and shell**

The overview provides search, ability/status filters, phase progress and cards. `ScenarioApp` loads its fixed key, renders loading/not-found/not-ready states, status strip, project summary, workbench slot, workflow, metrics, risks and generated curl example. Use the approved graphite/steel-blue/fog/amber tokens, visible focus, responsive stacking and reduced-motion styles.

- [ ] **Step 4: Verify build**

Run: `npm run build` in `frontend/frontend_admin`
Expected: Vite exits 0 and all lazy imports resolve.

- [ ] **Step 5: Commit**

Run: `git add frontend/frontend_admin/src/views/ai/scenarios frontend/frontend_admin/src/router/index.js && git commit -m "feat: add phase one scenario pages"`

### Task 7: Four production workbench components

**Files:**
- Create: `frontend/frontend_admin/src/views/ai/scenarios/workbenches/SegmentationWorkbench.vue`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/workbenches/VehicleReidWorkbench.vue`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/workbenches/PlateDetectionWorkbench.vue`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/workbenches/ObbDetectionWorkbench.vue`
- Create: `frontend/frontend_admin/src/views/ai/scenarios/components/ResultPanel.vue`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/ScenarioApp.vue`
- Modify: `frontend/frontend_admin/src/views/ai/scenarios/scenarios.css`

**Interfaces:**
- Consumes: scenario detail and `scenarioApi.infer`
- Produces: a shared `completed(result)` event and consistent busy/error/empty states

- [ ] **Step 1: Add serialization edge-case tests**

Test positive/negative points, box undo state, multiple ReID galleries, plate detector fields, and OBB fields. Run and verify at least one new assertion FAILS before adjusting utilities.

- [ ] **Step 2: Implement shared result panel and segmentation workbench**

Provide drag/drop input, image preview, canvas point/box prompts, undo/clear, supported precision/mode controls, busy state, mask preview, area/ratio/interaction metrics, JSON/image download and retained input after failure. Reuse interaction logic from the existing segment page without modifying that page. Do not expose or send `conf` because the SAM runtimes do not consume it.

- [ ] **Step 3: Implement ReID workbench**

Provide query plus multi-gallery upload, thumbnails, threshold, ranked similarity results, match/reject state, structured timeline-ready result and JSON download. Link to existing MTMC page for full video workflow.

- [ ] **Step 4: Implement plate and OBB workbenches**

Both provide image upload, conf/imgsz, overlay canvas, result table and JSON download. Plate adds crop previews and an explicit detector-only/OCR-link status. OBB renders four-point polygons, angle/coordinate details and selected-object perspective preview when returned.

- [ ] **Step 5: Verify utilities and build**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`
Run: `npm run build` in `frontend/frontend_admin`
Expected: tests PASS and build exits 0.

- [ ] **Step 6: Commit**

Run: `git add frontend/frontend_admin/src/views/ai/scenarios && git commit -m "feat: add scenario production workbenches"`

### Task 8: Navigation, documentation, and complete verification

**Files:**
- Modify: `backend/seed.py` only if menu seeding is the established navigation source and changes do not overlap user edits; otherwise expose the overview through an existing safe navigation location.
- Modify: `backend/docs/openapi_examples.md`
- Modify: `README.md` only if it already catalogs application modules.

**Interfaces:**
- Consumes: completed backend and frontend routes
- Produces: discoverable navigation and operator examples

- [ ] **Step 1: Add discoverability without overwriting user changes**

Inspect the current diff of `backend/seed.py` before editing. If its menu section is untouched, add one “模型场景” parent/overview entry and nine children with existing permission conventions. If overlapping edits exist, leave seed untouched and add a non-invasive link from the model list page only after reviewing its current diff.

- [ ] **Step 2: Add Open API examples**

Document list/detail and one multipart infer example per workbench type using placeholder credentials. Document readiness booleans and controlled errors.

- [ ] **Step 3: Run backend phase-one suite**

Run: `python -m pytest backend/unittests/test_model_scenarios.py backend/unittests/test_model_scenario_api.py backend/unittests/test_model_scenario_inference.py backend/unittests/test_openapi_model_scenarios.py backend/unittests/test_openapi_catalog.py backend/unittests/test_security_open.py -q`
Expected: all selected tests PASS with zero failures.

- [ ] **Step 4: Run full backend regression suite**

Run: `python -m pytest backend/unittests -q`
Expected: PASS. If environment/model-dependent tests are skipped, report the exact skip count and reasons; do not represent skips as executed inference coverage.

- [ ] **Step 5: Run frontend verification**

Run: `node --test frontend/frontend_admin/src/views/ai/scenarios/scenarioState.test.mjs`
Run: `npm run build` in `frontend/frontend_admin`
Expected: Node tests PASS and Vite exits 0.

- [ ] **Step 6: Review requirements and working tree**

Check all nine URLs, four workbench mappings, three management endpoints, three Open API endpoints, readiness states, download actions, responsive/focus/reduced-motion CSS and error handling against the spec. Run `git diff --check` and `git status --short`; distinguish pre-existing user changes from this feature.

The diff check must run from the repository root and include all owned tracked and untracked files before staging; resolve every whitespace error before the final commit.

- [ ] **Step 7: Commit documentation/navigation**

Stage only files owned by this task and commit: `git commit -m "docs: document model scenario applications"`.
