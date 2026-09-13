# Phase 1 ship blockers report

## Scope

Final production hardening for the first nine model scenarios. User-owned changes in `backend/inference.py`, `backend/seed.py`, `backend/unittests/test_omdet.py`, and the two existing frontend view files were not edited or staged by this work.

## Changes

- Replaced weak P2 marker validation with a shared side-effect-free production manifest contract.
- Required exact `artifactFile` basename binding and a 64-hex SHA256 matching the selected artifact.
- Applied the same trusted manifest/hash contract to EfficientSAM.
- Rejected compatible multi-weight directories as ambiguous before inference.
- Required a positive numeric Content-Length on signed POST inference before signature/body parsing; returned canonical 411/400/413 Open API envelopes with request IDs.
- Preserved bodyless GET list/detail signing with absent or zero Content-Length.
- Replaced legacy Open API examples with the sole canonical query and ordered multipart signing protocol.
- Added manifest schemas and SHA256 generation commands.

## TDD evidence

- RED: five missing/invalid/nonpositive Content-Length cases reached signature verification/body handling.
- GREEN: `test_openapi_model_scenarios.py -k "content_length or signed_get_allows"`: 7 passed.
- RED: missing artifact/hash, traversal, wrong artifact, invalid/wrong hash, directory ambiguity, and EfficientSAM without manifest were accepted or reported under weaker reasons.
- GREEN: focused contract cases: 8 passed.
- Regression: `test_openapi_model_scenarios.py`: 29 passed.
- Regression: `test_model_scenario_inference.py`: 65 passed.
- `py_compile` passed for changed Python production and test modules.
- `git diff --check` passed.
- Full `test_model_scenario_api.py` progressed through 19 passing cases without failure but exceeded the 360-second execution limit; focused new contract tests passed separately.

Warnings observed are pre-existing SQLAlchemy datetime/query deprecations, MobileSAM registry warnings, and a workspace `.pytest_cache` permission warning; no test failure was hidden by them.

## Precision follow-up

- EfficientSAM manifests now support explicit `artifacts.fp32` and `artifacts.int8` bindings; one or both may be published.
- Readiness exposes `supportedPrecisions`; inference rejects unpublished values and resolves the exact manifest-bound file before calling the adapter.
- The segmentation workbench renders only server-published precision options.
- Restored the general Open API bridge, compact alias, async worker, webhook, gateway, and metrics documentation without restoring the obsolete multipart signing rules.
- Precision contract tests: 4 focused tests passed (dual publication, invalid hash, unpublished precision, exact int8 path).
- Combined inference and Open API security regression: 95 passed.
- Frontend scenario Node tests: 23 passed; Vite production build passed.
