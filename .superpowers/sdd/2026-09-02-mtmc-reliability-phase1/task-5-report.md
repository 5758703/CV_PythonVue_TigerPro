# Task 5 report — MTMC evidence and shutdown consistency

Base checked: `19ad19db` (`fix: make MTMC association evidence atomic`).

## Commands and real output

```text
pytest backend/unittests/test_mtmc_evidence_consistency.py -q -p no:cacheprovider
6 passed, 10 warnings in 37.99s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_p2.py backend/unittests/test_mtmc_tracklet.py -q -p no:cacheprovider
64 passed in 3.45s

python -m py_compile backend/services/vehicle_reid_feat.py backend/services/mtmc_associator.py backend/services/mtmc_engine.py backend/services/mtmc_persist.py
exit 0

git diff --check
exit 0
```

## Round 2/5 follow-up

Self-initiated worker shutdown now schedules one daemon coordinator. The
coordinator joins the original workers after the caller exits, then takes the
same finalization lock to flush builders and clean uploads exactly once.

Promotion installs a session GID alias while holding the candidate lock after
the database decision succeeds and before the in-memory merge/rekey. The
association-record persistence boundary canonicalizes returned global IDs,
source/candidate evidence IDs, builder assignment, and downstream event state
under that lock. Rejection deliberately installs no alias.

```text
RED: 2 failed, 10 passed (self-worker finalizer and stale-GID persistence)
GREEN: 12 passed, 26 warnings in 57.85s
Final focused + MTMC regression: 89 passed, 26 warnings in 58.89s
python -m py_compile backend/services/mtmc_engine.py: exit 0
git diff --check: exit 0
```

## Round 3/5 follow-up

When alias normalization collapses a candidate evidence target and candidate
ID to the same global, the engine now rewrites it as `long_term` evidence and
does not create a pending self-pair. The association record returns the
canonical Global so downstream frame event/pass/cache code keeps the retained
ID.

Tracklet finalization now holds the session candidate lock through aggregate
association and `persist_tracklet`, preventing a promotion from splitting that
final persistence boundary.

```text
RED: 2 failed, 12 passed (self-pair and finalize/promotion barrier)
GREEN: 14 passed, 26 warnings in 56.67s
Final focused + MTMC regression: 91 passed, 26 warnings in 61.24s
git diff --check: exit 0
```

The sandbox account cannot enumerate its default pytest temporary directory;
the two pytest commands above were run with `PYTEST_ADDOPTS=--basetemp
.pytest-task5-final`, and that workspace-only temporary directory was removed
afterward.

## Changes

- Vehicle OCR observations now normalize punctuation/likely character
  confusions and use confidence-weighted multi-frame voting when finalizing a
  vehicle tracklet.
- Vehicle visual evidence looks up an existing candidate prototype and never
  supplies the current embedding as both similarity operands.
- `associate_with_evidence` retains evidence in a call-local variable and only
  mirrors it into the legacy `last_evidence` accessor after constructing the
  atomic result.
- Shutdown signals workers, joins them, finalizes all builders, then removes
  upload artifacts.
- Candidate promotion and rejection update every matching pending persisted
  pair in one commit; promotion also updates associated tracklet rows and
  failure rolls the session back.

## Self-review

- Concurrent association coverage asserts distinct evidence instances and a
  matching target ID for each result.
- Existing `associate(...) -> GlobalTrack` remains a compatibility wrapper.
- Promotion/rejection coverage uses a real temporary SQLite database and
  verifies duplicate related candidate rows are resolved together.
- Worker join skips only the current thread; builder flush remains serialized
  by the camera lifecycle lock.

## Hashes (SHA-256, pre-commit worktree)

```text
backend/services/vehicle_reid_feat.py EAFB70297C04EEDE3FCE2FD4E223775C020C6E7C7262EDE54FCE8E25F0433328
backend/services/mtmc_associator.py 1919AEEC5BFF46CD4F7EB74003E329BAED1D910E72E9A53885DE4FC867F65C9A
backend/services/mtmc_engine.py 36B71651263555CC38615B62A4712C8368E881024B84EE127A594615F412FD29
backend/services/mtmc_persist.py 35681D7F64908ED288FAB9FE417CE206DF7771D5F60DE6FEEF4B0899EF364D5C
backend/unittests/test_mtmc_evidence_consistency.py 6C2F20050E2AEE6230FA4A39AB247A0095E881E3FE357A35162EE11C0CE6CA32
```

## Concerns

- Tests pass, but SQLite/SQLAlchemy emits existing `datetime.utcnow()`
  deprecation warnings from model defaults and `mtmc_persist._utc_now`; this
  task does not alter the application-wide timestamp storage convention.

## Round 1/5 follow-up

Added RED/GREEN coverage for global-ID rewrite across candidate pairs,
tracklets, track events, association-edge source/target fields, cross-camera
events, vehicle passes and vehicle global identities.  Promotion now performs
these changes in the resolver's single database commit, and rolls back on any
exception.

The engine validates the two live globals under a session candidate lock,
persists the decision first, then merges in-memory tracks and rekeys live
event/pass/camera caches. A failed persistence result leaves associator tracks
and live candidate rows unchanged. Rejection now removes the live candidate
relation and promotes its local global to an independent confirmed track only
after persistence succeeds.

Shutdown has a session finalization lock and once flag. It will not flush
builders or delete upload data until every non-self worker has exited after the
join timeout; concurrent successful callers observe exactly one finalization.

```text
RED: 4 failed, 6 passed (required failure modes observed)
GREEN: pytest backend/unittests/test_mtmc_evidence_consistency.py -q -p no:cacheprovider
10 passed, 26 warnings in 58.20s

pytest backend/unittests/test_mtmc.py backend/unittests/test_mtmc_p2.py backend/unittests/test_mtmc_tracklet.py backend/unittests/test_mtmc_tracklet_lifecycle.py -q -p no:cacheprovider
77 passed in 3.58s

git diff --check
exit 0
```
