# Phase 1 Model Scenarios — Security Hardening Report

Date: 2026-09-13

## Delivered

- HMAC canonical request covers method, normalized path, normalized query (duplicates retained and encoded key/value sorted), timestamp, nonce, normalized Content-Type, and payload hash.
- Multipart payload manifests preserve original part index/order. File entries cover field name, safe filename, part Content-Type and content SHA-256; form entries cover field name and value. Signature comparison remains constant-time.
- Content-Length aggregate rejection occurs before body parsing. Multipart parsing then enforces part count, file count, per-file bytes, aggregate file bytes, safe filenames and known field names. The dispatcher retains capability-specific form/file allowlists.
- Nonce, shared DB limiter and credential lookup failures return the standard `open_error` envelope with `requestId`. Audit writes are best effort and cannot replace the response if audit storage fails.
- Gateway startup now runs the same idempotent schema migration as the admin app. SQLite migrations issue one `ADD COLUMN` per statement and create the nonce/rate tables before migration.
- SAM `conf` was removed from its registry/UI contract and documented as rejected. Resource limits and signing algorithms are synchronized in configuration, OpenAPI and client examples.

## TDD evidence

RED cases reproduced before implementation:

- Query mutation and multipart filename/order mutation were not authenticated.
- Unknown multipart file fields and excess part counts were not rejected before inference.
- DB rate limiter exceptions escaped Flask's JSON API envelope.
- Legacy gateway databases retained an `open_app` table without `ip_allowlist`; initial combined SQLite `ADD COLUMN` syntax also failed.

GREEN verification:

- `test_openapi_model_scenarios.py`: 23 passed after adding signing/resource/DB-failure coverage.
- Gateway migration + topology migration + OpenAPI security: 26 passed.
- Frontend scenario state: 23 passed.
- Frontend production build: exit 0 (only existing Rollup chunk-size/pure-annotation warnings).
- Model scenario inference: final focused run reached 64 passed and one fixture-isolation failure; the stale production manifest fixture was then removed in teardown. A final rerun was not completed before report generation.

## Verification limitations / remaining evidence

- The combined feature command timed out after 240 seconds while still running, without reporting a failure before timeout.
- A full `backend/unittests` run was not completed in this hardening pass. The previously reported unrelated `imageio_ffmpeg` environment failure therefore remains the known baseline distinction, not a fresh result.
- Temporary pytest base directories under `backend/.tmp_pytest_*` are untracked test artifacts and are intentionally not staged.
