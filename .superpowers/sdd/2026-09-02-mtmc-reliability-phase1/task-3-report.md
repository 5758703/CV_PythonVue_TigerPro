# Task 3 report — directed topology and authoritative final score

Base HEAD: `51e4adc55159279af962a2b534b825221b303fa8`.

Task brief SHA-256: `795464709F79655B3FF7DA50B7CB86D0DB2DBE6194C20368C0477C3AED3A0B6E`.

## TDD evidence

RED command:

```text
pytest backend/unittests/test_mtmc_topology_policy.py -q -p no:cacheprovider
FFFFF                                                                    [100%]
5 failed in 0.46s
```

The failures demonstrated auto-created reverse edges, zero-time acceptance for
non-overlap edges, ignored weights/time in `final`, raw-ReID tier bypass, and
missing pipeline topology injection. The immutability test was also run RED:

```text
pytest backend/unittests/test_mtmc_topology_policy.py::test_topology_rule_is_immutable -q -p no:cacheprovider
1 failed in 0.39s
```

GREEN command/output:

```text
pytest backend/unittests/test_mtmc_topology_policy.py -q -p no:cacheprovider
6 passed in 0.33s
```

Required regression command/output (the explicit basetemp avoids the sandboxed
default Windows temp directory):

```text
pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_p2.py -q -p no:cacheprovider --basetemp .tmp_pytest_mtmc
61 passed in 3.77s
```

`git diff --check` exited 0 with no findings.

## Changes

- Added frozen `TopologyRule`; topology inputs are directed and never synthesize
  a reverse edge. Persisted edges default to `edgeType: non_overlap`.
- Missing edges in a loaded topology reject cross-camera association. Overlap
  edges explicitly accept `dt=0`; auto-generated upload edges are overlap.
- `final` multiplies appearance/identity score, topology weight, time likelihood,
  recency, and established-cross-camera evidence. All long-term tiers use
  `final`, so raw ReID cannot bypass a low policy score.
- Added a shared database-topology loader used by both API and pipeline session
  entry points.
- Added persisted `edge_type` on camera topology and retained all existing CRUD
  JSON fields.

## Self-review

- Verified the complete embedding-space key remains untouched; this task does
  not alter gallery or embedding lifecycle handling.
- Verified API and pipeline both supply database topology to `start_session`.
- Verified configured empty topology remains explicit (`topology_edges=[]`) and
  therefore rejects cross-camera edges rather than silently auto-generating one.

## Concerns

- Direct, legacy `MtmcAssociator()` construction without any topology keeps its
  prior time-window behavior for unit-call compatibility. Production API and
  pipeline sessions always load topology (including an explicit empty list), so
  they use strict missing-edge rejection.
- Existing deployed databases need a schema migration to add
  `camera_topology.edge_type`; this repository has no migration directory.
- The local test environment lacked three already-pinned runtime dependencies;
  installed `Flask-SQLAlchemy==3.1.1`, `Flask-Cors==4.0.1`, and
  `Flask-JWT-Extended==4.6.0` solely to execute the required suite.
