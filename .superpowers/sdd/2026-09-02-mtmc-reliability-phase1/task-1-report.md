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
