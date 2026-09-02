# Task 1 report — Correct ReID Input Shapes and Isolate Model Spaces

## Status

DONE_WITH_CONCERNS

## Failed-test evidence (RED)

Before production changes:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
FFFFF
5 failed in 2.41s
```

The failures were expected and targeted the required gaps:

- a declared `[1, 3, 256, 128]` ONNX input was preprocessed as `(1, 3, 224, 224)`;
- `extract_person_embeddings` did not exist (two tests);
- `_match_gallery` still accepted one embedding plus unrelated model keys;
- `fuse_similarity_scores` did not exist.

## Implementation summary

- Parse the ONNX input's NCHW height and width directly, reject dynamic/invalid spatial shapes, and reject empty outputs.
- Add `extract_person_embeddings`, which keeps normalized Strong and Youtu vectors keyed by stable model-space keys and returns per-backend readiness/error metadata.
- Preserve `extract_person_embedding` as a compatibility wrapper selecting one unmodified best space; it no longer pads, trims, or averages model spaces.
- Add calibrated-score fusion with available-weight renormalization.
- Make gallery lookup accept a `{model_key: embedding}` mapping and query only matching spaces; dimension mismatch returns no match rather than attempting comparison.
- Surface ReID backend readiness in person item metadata.

## Tests

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
5 passed in 0.33s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider
57 passed, 4 errors in 11.73s
```

The second required command's four errors occurred during pytest fixture setup because the sandbox denied access to `C:\Users\Administrator\AppData\Local\Temp\pytest-of-Administrator`; no test assertion failed. Re-running the same tests with pytest's temporary base inside the authorized workspace passed:

```text
pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider --basetemp .pytest-mtmc-tmp
61 passed in 2.21s
```

The temporary directory was removed after the run.

## Commit

`fix: correct MTMC ReID model spaces`

## Self-review / concerns

- `git diff --check` passed.
- The legacy single-embedding callers remain supported through the compatibility wrapper.
- Gallery vectors are now compared only under their own model key and matching dimension.
- Concern: the unmodified required regression command cannot create/read its default system pytest temp directory in this sandbox. The explicit workspace-basetemp rerun passed all 61 tests.

## Review-fix round 1

### Status

DONE_WITH_CONCERNS

### RED / GREEN evidence

The added review-regression tests initially failed as expected:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
5 passed, 5 failed
```

The failures showed the missing Tracklet model-key API, missing Global `embedding_spaces` association API, inactive score-fusion decision path, non-dimension-scoped Gallery cache, and absent truth metadata. After the implementation:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
10 passed in 0.42s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider --basetemp .pytest-mtmc-tmp
61 passed in 4.01s
```

`pytest backend/unittests/test_mtmc_p2.py -q -p no:cacheprovider --basetemp .pytest-mtmc-p2-tmp` collected three tests but two require the unavailable optional `flask_sqlalchemy` package; the remaining test passed. This is an environment dependency error, not an assertion regression.

### Finding resolution

1. Tracklet observations, aggregates, Global prototypes, active-gallery entries, score comparisons, updates, and global merges now use exact `(model_key, dim, version)` spaces. No ReID vector padding/trimming remains on those paths.
2. `_match_gallery` groups calibrated per-space scores by candidate identity and uses `fuse_similarity_scores`; `_reid_score_weights` maps `MtmcConfig.fuse_weight_strong` (already populated from the existing route `fuseWeightStrong`) to the actually available Strong/Youtu spaces and renormalizes missing backends.
3. Persistent Gallery SQL filtering, cache keys, and FAISS keys now include query dimension. Invalid stored embeddings generate observable warning logs and are skipped rather than silently compared.
4. Runtime metadata reports actual `availableModelSpaces`, `associationModelKey`, `galleryModelKey`, per-backend readiness, and the actual active backend.
5. Added regressions cover Strong→Youtu fallback within one Tracklet, isolated Global prototype matching, production score fusion, same-key different-dimension Gallery caching, and fallback metadata truth.

### Changed files

- `backend/services/mtmc_active_gallery.py`
- `backend/services/mtmc_associator.py`
- `backend/services/mtmc_engine.py`
- `backend/services/mtmc_tracklet.py`
- `backend/services/reid_gallery.py`
- `backend/services/strong_reid.py`
- `backend/unittests/test_mtmc_reid_runtime.py`

### Review-fix commit

`b55b0e8f5e506e3cc257ed2bd35ee3741289389d fix: isolate MTMC ReID prototype spaces`

## Review-fix round 2

### RED / GREEN evidence

Before the second implementation pass, the focused runtime test reported five expected failures:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
10 passed, 5 failed
```

They proved that a below-threshold Youtu score was dropped before fusion, per-space versions were not accepted/preserved, extraction did not expose per-space versions, and a configured zero weight could suppress the only live backend. After the minimal fix:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider
15 passed in 0.47s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider --basetemp .pytest-mtmc-tmp
61 passed in 2.75s
```

### Finding resolution

1. Gallery matching now retains the raw Top-1 candidate identity fields for every model space. `_match_gallery` aligns these by identity, fuses calibrated scores, and applies the configured threshold exactly once after fusion. The explicit `0.80 * 0.75 + 0.40 * 0.25 = 0.70` case at threshold `0.48` is covered.
2. `modelVersionsBySpace` now flows from extraction into `TrackletBuilder`; its aggregation tuples retain `(model_key, dim, version)`, so same-key/same-dimension distinct asset versions remain separate through Global/Active Gallery input.
3. Score weights are clamped to `[0, 1]`, normalized across available spaces, and forced to `1.0` for a sole live backend. Both `Strong=1/Youtu-only` and `Strong=0/Strong-only` cases are covered.

### Changed files

- `backend/services/mtmc_engine.py`
- `backend/services/mtmc_tracklet.py`
- `backend/services/reid_gallery.py`
- `backend/services/strong_reid.py`
- `backend/unittests/test_mtmc_reid_runtime.py`

### Review-fix commit

`748cc41eda00035d6769c4d7c089093a3597db91 fix: finalize MTMC ReID score fusion`

## Blocker-resolution pass

### RED / GREEN evidence

The three remaining P1 areas were captured by seven failing assertions before
production changes:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider --basetemp .pytest-task1-red
15 passed, 7 failed
```

After the fixes:

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider --basetemp .pytest-task1-green2
22 passed in 0.79s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider --basetemp .pytest-task1-regression
61 passed in 6.38s
```

### Finding resolution

1. `_match_gallery` now iterates identity/group pairs and returns the identity
   belonging to the winning fused-score group. A regression uses conflicting
   Strong and Youtu Top-1 identities.
2. `fuseWeightStrong` preserves explicit zero, defaults only for `None`, and is
   bounded to `[0, 1]` through one shared parser used by the route and runtime.
3. Registered gallery vectors now persist `model_version`. SQL selection,
   in-memory cache, FAISS index/cache, direct lookup, and MTMC fusion all carry
   `(model_key, dim, model_version)`. Legacy NULL-version rows form an isolated
   versionless space; an explicitly versioned query never reads them.
4. Existing databases receive the nullable `reid_embedding.model_version`
   column through the project's lightweight migration mechanism. New
   registrations use the actual resolved ONNX filename when available.

### Changed files

- `backend/app.py`
- `backend/models/reid.py`
- `backend/routes/mtmc.py`
- `backend/routes/reid.py`
- `backend/services/mtmc_engine.py`
- `backend/services/reid_gallery.py`
- `backend/services/strong_reid.py`
- `backend/unittests/test_mtmc_reid_runtime.py`

### Concerns

- Existing legacy registration rows remain intentionally unmatched by an
  explicitly versioned runtime query until they are re-enrolled. This is a
  deliberate fail-closed policy preventing cross-version prototype mixing.

## Independent-review fix pass 1

### RED / GREEN evidence

```text
pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider --basetemp .pytest-review-red
22 passed, 7 failed

pytest backend/unittests/test_mtmc_reid_runtime.py -q -p no:cacheprovider --basetemp .pytest-review-green
29 passed in 0.71s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider --basetemp .pytest-review-regression
61 passed in 2.64s
```

### Finding resolution

1. Image recognition, Gallery search and video search now retain the resolved
   ONNX filename from `extract_feature` and pass it to Gallery lookup as the
   precise model version. Service-level regressions cover recognize and Top-K
   search hits from versioned vectors.
2. Association score maps and weight maps retain complete
   `(model_key, dim, model_version)` keys. Same-key vectors from different
   versions can no longer overwrite one another before fusion.
3. Gallery failures are logged and surfaced in both item `galleryStatus` and
   session `runtime.gallery`; processing remains available in degraded mode.
4. Non-finite fusion weights use the safe `0.65` default consistently. Explicit
   finite zero remains valid and out-of-range finite values remain bounded.

### Changed files

- `backend/inference.py`
- `backend/services/mtmc_associator.py`
- `backend/services/mtmc_engine.py`
- `backend/unittests/test_mtmc_reid_runtime.py`

### Concerns

- The regression uses inference service entry points because importing the
  Flask route stack requires the optional `flask_sqlalchemy` dependency that is
  unavailable in this execution environment.
