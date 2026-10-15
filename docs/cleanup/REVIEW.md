# Review of `pre-cleanup..cleanup/qualite`

- Base: `pre-cleanup` = `b1e18e6` (the tag is local only, see M10). Head: `cleanup/qualite` = `e266784`. 60 commits, 219 files.
- Scope: every file under `backend/`, plus `tests/unit`, `tests/performance`, `tests/conftest.py`, CI, dependency files, scripts and docs. `tests/oracle` and `tests/integration` were checked only for integrity.
- Method: I read each source diff (with `-w`, so formatting is ignored), compared moved code against the old handlers, listed every `except` that was narrowed and its fallback contract, and diffed the assertions of every changed test. I reproduced the suspicious paths against both trees (`git archive` copies in the scratchpad, so the repo was not touched).
- State check:
  - `sha256sum -c docs/cleanup/ORACLE.sha256` passes.
  - Frozen tests are unchanged since `57e593d`.
  - Full suite on an isolated copy of the branch: **1010 passed**.
  - The repo working tree is untouched.

Severity scale:
- **bloquant**: breaks the mission's "no functional change" rule, has a concrete reproduced failure scenario, and either defeats an explicit robustness contract or hides it behind an edited test. Fix before the PR.
- **important**: a real behaviour change on a failure path, or a test adapted in a way that hides one. It should be fixed, or at least recorded in DECISIONS.md.
- **mineur**: low-probability path, documentation, or dead code.

## Summary

| # | Severity | Where | Topic |
|---|---|---|---|
| B1 | bloquant | `backend/src/ingestion/processor.py:476` (called at :392); `tests/unit/test_ingestion_processor.py:387` | A BM25 drain failure now fails an ingestion whose FAISS write already succeeded. The guarding test was edited so it still passes. |
| B2 | bloquant | `backend/src/api/dependencies.py:124`, `backend/main.py:202`, `backend/src/rag_core/implementations/bm25_store.py:193` | A corrupt BM25 index on disk now disables ingestion entirely (before: warning, then dense fallback). |
| B3 | bloquant | `backend/src/ingestion/extractors.py:133` (and :164) | One bad PDF page now makes the whole document fail (before: the page was skipped). |
| I1 | important | `backend/src/services/rag_service.py:483` | A BM25 query failure no longer always degrades to dense-only; the user gets an SSE error event. |
| I2 | important | `backend/src/services/index_maintenance.py:75` | After a delete, a failed orphan cleanup now skips the BM25 resync. |
| I3 | important | `backend/src/services/document_upload.py:217` | A cleanup failure after a full queue turns the 503 into a 500 and leaves an orphaned record (every retry then gets 409). |
| I4 | important | `backend/src/email_service/smtp_client.py:77,82,151`; `tests/unit/test_email_service.py:177` | E-mail fallbacks were removed; the escalation test was rewritten onto another path. |
| I5 | important | several unit tests | Tests were adapted (`Exception` replaced by a listed type) instead of pinning the old behaviour. |
| M1 | mineur | `backend/src/services/rag_service.py:254` (via :497) | The FAISS RLock is now taken on the event loop in every hybrid query. |
| M2 | mineur | `backend/src/utils/log_parser.py:342`, `backend/src/utils/logs_reader.py:304` | Analytics fallbacks removed: `/admin/analytics/usage` can now return 500. |
| M3 | mineur | `backend/src/api/endpoints/health.py:137` | `disk-usage`: an unexpected error in one directory now marks the whole probe unhealthy. |
| M4 | mineur | `backend/src/rag_core/implementations/faiss_store.py:135,698,933` | The FAISS load fallback, the "existing document ids" fallback and the audit of a failed rebuild (`index_maintenance.py:193`) were narrowed. |
| M5 | mineur | `backend/src/llm_interface/implementations/mistral_api.py` | Mistral: unexpected exceptions are no longer wrapped in `LLMAPIError`. |
| M6 | mineur | `backend/src/auth/jwt_handler.py` | `verify_token` was narrowed: an unexpected error gives 500 instead of 401 (it still fails closed). |
| M7 | mineur | various | Dead code left in place, and documentation that is now false (`file_watcher`, unused models, a stale docstring and comments). |
| M8 | mineur | `docs/cleanup/DECISIONS.md` D0.1 | The `pre-cleanup` tag was never pushed. |

There are no security regressions. Details are in "Checked without findings" at the end.

---

## Blocking findings (bloquant)

### B1. BM25 drain rebuild: ingestion is no longer protected from a BM25 failure, and the test that guarded this was weakened

- **Where:**
  - `backend/src/ingestion/processor.py:476`: `except VectorStoreException` (before: `except Exception`) in `_maybe_rebuild_bm25_on_drain`.
  - This method is awaited inside the `try` of `_process_document_pipeline` (`processor.py:392`), after the FAISS upsert and persist have already succeeded.
  - The test `tests/unit/test_ingestion_processor.py:387` (`test_pipeline_bm25_rebuild_failure_is_non_fatal`) used to inject `RuntimeError("bm25 boom")`. It now injects `VectorStoreOperationError("bm25 boom")`.
- **What changed:** before, any failure of `snapshot_active_chunks()` or of `bm25_store.rebuild()` was logged ("BM25 rebuild failed at drain - continuing anyway") and the pipeline returned `True`. Now, anything outside `VectorStoreException` propagates to the pipeline's catch-all, so the pipeline returns `False`.
- **Why it matters:**
  - The docstring states the contract: "A BM25 failure is non-fatal (FAISS already holds the chunks)", and the test was written precisely to pin it.
  - The test was changed so that it fits the narrowed `except`. Its scenario (a `RuntimeError`) no longer passes on the new code.
  - Mission rule broken: no functional change, and tests must not be edited to hide a change.
- **Failure scenario:**
  1. A bulk load on a large corpus makes the bm25s rebuild raise `MemoryError`. That type is not in `INDEX_BACKEND_ERRORS`, so it is not wrapped. (`snapshot_active_chunks()` is not wrapped either.)
  2. The document is already in FAISS and persisted, yet it is marked `error` ("Processing pipeline failed").
  3. `AsyncQueueManager` retries it up to `ingestion_max_retries` (5).
  4. Every retry re-embeds the whole document: a paid Mistral call, a budget reservation, then a new upsert.
- **Reproduction:** `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/bm25_drain.py` is the original test body (with `RuntimeError`).
  - pre-cleanup: `pipeline success: True`
  - cleanup/qualite: `pipeline success: False`
- **Fix:** treat the drain rebuild as a worker boundary: `except Exception  # noqa: BLE001 - best effort: FAISS already holds the chunks`. Restore `RuntimeError` in the test.

### B2. A corrupt BM25 index on disk now disables ingestion entirely

- **Where:**
  - `backend/src/api/dependencies.py:124`, `get_bm25_store()`: `except RetrievalError` (before: `except Exception  # noqa: BLE001 - never fail startup on a bad/missing index`).
  - `backend/main.py:202`, `_ensure_bm25_index()`: `except RetrievalError` (before: `except Exception`).
  - `backend/src/rag_core/implementations/bm25_store.py:193`, `load()`: only wraps `INDEX_BACKEND_ERRORS`. That tuple has no `EOFError`, even though `faiss_store.load()` adds `EOFError` explicitly (`faiss_store.py:698`).
- **What changed:** `np.load` on a truncated `.npy` file raises `EOFError`. That error now escapes `load()` and `get_bm25_store()`. The first call to `get_bm25_store()` happens while `IngestionProcessor` is being built in `_start_ingestion` (`main.py:166`). The exception aborts the whole block: `set_ingestion_processor()` (`main.py:174`) and the re-queueing of pending documents are skipped.
- **Why it matters:** an explicit contract is broken ("never fail startup on a bad/missing index"), and the effect is severe: no ingestion until someone deletes the index by hand.
- **Failure scenario:**
  1. After a crash or power loss, or a partial restore, a file in `data/bm25/index` (e.g. `data.csc.index.npy`) is truncated. bm25s writes into a temporary directory and renames it, with no fsync of the files.
  2. On the next start, the warning "Failed to initialize ingestion processor" is logged.
  3. Every upload (`/documents/upload`, `/admin/documents/upload`) and every reprocess then fails with 500 (`get_ingestion_processor` raises `RuntimeError`).
  4. Documents left `pending` are never re-queued.
  - Before: a warning, an empty store, hybrid search falling back to dense-only, and ingestion working.
- **Reproduction:** `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/bm25_eof.py` builds the index, then empties one `.npy` file. `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/bm25_getter.py` then calls `get_bm25_store()` on it.
  - pre-cleanup: "returned a store (degraded gracefully)"
  - cleanup/qualite: `get_bm25_store RAISED: EOFError - No data left in file`
- **Fix:** restore the catch-all, with justification, in `get_bm25_store` and `_ensure_bm25_index` (these are startup boundaries). Also add `EOFError` (and ideally `pickle.UnpicklingError`) to the wrapping in `Bm25LexicalStore.load`, consistent with FAISS.

### B3. A malformed PDF page now makes the whole document fail

- **Where:**
  - `backend/src/ingestion/extractors.py:133`: the per-page loop now catches `(pypdf.errors.PyPdfError, *_PARSER_ERRORS)` (before: `except Exception`).
  - The outer handler (`extractors.py:164`) has the same list, so any other exception escapes without being wrapped in `ExtractionError`.
- **What changed:** before, a page that failed `extract_text()` was logged ("Failed to extract text from page N") and skipped; the rest of the document was indexed. Now, `ZeroDivisionError`, `OverflowError`, `struct.error`, `zlib.error`, `AssertionError` and `decimal.InvalidOperation` all abort extraction of the whole file. None of them are in `_PARSER_ERRORS`, and pypdf is known to raise them on broken content streams or fonts.
- **Why it matters:** the per-page catch-all was a deliberate robustness feature on the most common ingestion path. The oracle only ingests clean files, so it does not see the change.
- **Failure scenario:**
  1. A 200-page enterprise PDF has one page with a degenerate font matrix, and `extract_text()` raises `ZeroDivisionError`.
  2. Before: 199 pages were indexed.
  3. Now: the document goes to status `error`, is retried 5 times and is never indexed.
  4. The reader view `/documents/{id}/full` also loses its `content` (`document_reader._extract_text` falls back to `None`).
- **Reproduction:** `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/pdf_page_error.py` (2-page PDF; page 2 raises `ZeroDivisionError`).
  - pre-cleanup: `extracted OK (bad page skipped): 'Texte de la page un.'`
  - cleanup/qualite: `whole extraction FAILED: ZeroDivisionError`
- **Fix:** restore `except Exception  # noqa: BLE001 - best effort per page` in the page loop. Keep the outer handler wide enough that any parser failure becomes an `ExtractionError`.

---

## Important findings

### I1. Hybrid search: a BM25 query failure no longer always degrades to dense-only

- **Where:** `backend/src/services/rag_service.py:483`, `except RetrievalError` (before: `except Exception  # noqa: BLE001 -- any lexical-store failure degrades to dense-only`).
- **Change:** `Bm25LexicalStore.query` only wraps `INDEX_BACKEND_ERRORS`, so anything else (`ArithmeticError`, `MemoryError`, `AssertionError`, ...) now ends the chat stream with an SSE `error` event instead of a dense-only answer. The comment above the block still promises the old behaviour.
- **Scenario:** a bm25s failure on a degenerate corpus. Hybrid search is on by default (`hybrid_search_enabled=True`), so every chat question goes through this code.
- **Fix:** this is an explicit degradation boundary; restore the catch-all with its justification.

### I2. Deletion: a failed orphan cleanup now skips the BM25 resync

- **Where:** `backend/src/services/index_maintenance.py:75` (`_clean_orphans_if_fragmented`, `except RetrievalError`).
- **Change:** before, the orphan cleanup and the BM25 rebuild sat in two independent `try` blocks. Now, a cleanup error that is not a `RetrievalError` propagates out of `remove_document_from_indexes`. The BM25 rebuild that follows it in the same function is skipped, and the deletion only logs "Error removing document from vector store".
- **Scenario:** `clean_orphans` fails after `optimize()` has renumbered the chunk ids (for example, the persist step raises an error outside the list). BM25 keeps the old ids, so hybrid hits point to the wrong chunks, or are dropped as "index drift", until the next ingestion.
- **Fix:** restore the two separate best-effort blocks.

### I3. Upload with a full queue: a cleanup failure turns 503 into 500 and leaves an orphaned record

- **Where:** `backend/src/services/document_upload.py:217`, `except (SQLAlchemyError, ValueError, OSError)` (before: `except Exception`).
- **Change:** any other exception raised by `doc_repo.delete` or `unlink` now escapes `_reject_queue_full`. `_queue` turns it into a 500 "Failed to queue document for processing" instead of a 503. The pending record and the stored file stay, and every retry of the same file gets 409. That is exactly the case the comment on lines 211-213 says to avoid.
- **Scenario:** low probability (it needs an unexpected error during the rollback), but the effect is permanent for that file.
- **Fix:** restore the catch-all; this is a best-effort cleanup.

### I4. E-mail: fallbacks removed, and the escalation test rewritten

- **Where:**
  - `backend/src/email_service/smtp_client.py:82`: `send_notification_email` lost its `try/except Exception` entirely.
  - `smtp_client.py:151`: `_send_email` narrowed.
  - `smtp_client.py:77`: `send_escalation_email` narrowed to rendering errors.
  - `tests/unit/test_email_service.py:177-180`: the test used to make `_send_email` raise `Exception("SMTP Error")`; it now makes `_generate_escalation_html` raise a `TemplateError`.
- **Change:**
  - `POST /admin/test-email` now answers 500 "Email service test failed" instead of `200 {success: false, "Failed to send test email..."}` when an exception falls outside the list.
  - `POST /chat/escalate` now answers "Une erreur s'est produite lors de l'envoi de votre demande." instead of "Impossible d'envoyer votre demande pour le moment...".
  - The original scenario (`_send_email` raising) is no longer tested.
- **Fix:** restore the catch-alls in both public methods (or in `_send_email`), and the original test.

### I5. Unit tests adapted to the narrowed `except` clauses instead of pinning the old behaviour

Beyond B1 and I4, several tests swapped `Exception(...)` for a listed type so they pass the new filters. Each swap hides a behaviour change for any other exception type:

- `tests/unit/test_auth_jwt_handler.py:222`: `jwt.InvalidKeyError` instead of `Exception`.
- `tests/unit/test_auth_jwt_handler.py:304`: `ValueError` instead of `Exception`.
- `tests/unit/test_ingestion_extractors.py`: `FileNotDecryptedError`, `PdfReadError` and `PackageNotFoundError` instead of `Exception`. Other parser errors are no longer converted into `ExtractionError` / `ProcessingError`.
- `tests/unit/test_email_service.py`: `SMTPConnectError` instead of `Exception`.
- `tests/unit/test_file_watcher.py`, the FAISS backup tests and the log tests: `RuntimeError` / `OSError` instead of `Exception`.
- The DB connection tests: `OperationalError` instead of `Exception`.

These adaptations are not recorded in D2.6 as behaviour changes. Each one should either restore the old behaviour or be justified in DECISIONS.md.

The 62 test deletions (D6.2) were checked by sampling (test_config env loading, the CORS `MagicMock` case, the health delegations, the auth middleware duplicates). Their stated reasons are accurate. Assertion counts were compared per file; apart from the cases above, nothing was weakened. The mutation tests added for chunking and fusion strengthen the suite.

---

## Minor findings (mineur)

### M1. The FAISS lock is taken on the event loop in the hybrid path

- **Where:** `backend/src/services/rag_service.py:254`. `_merge_and_attach_rrf_scores` calls `vector_store.snapshot_active_chunks()` (which takes the FAISS RLock). It is called synchronously from `_hybrid_retrieve` (`rag_service.py:497`), on the event loop.
- **Before:** it read `vector_store.metadata` directly, without the lock.
- **Measured** (20k chunks, `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/loop_stall.py` and `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/loop_stall_rebuild.py`):
  - While a `persist()` runs in a thread, the merge blocks the loop for 1.29 s. The old code also stalls about 1.0 s, through the GIL.
  - During an admin rebuild: 1.78 s (new) against 1.96 s (old).
- **Assessment:** the marginal impact is small here because FAISS already holds the GIL. On a slow disk, though, the new code also blocks for the whole fsync, which releases the GIL. It also goes against the convention stated in the code ("must never block the event loop").
- **Fix:** `active = await asyncio.to_thread(vector_store.snapshot_active_chunks)` in `_hybrid_retrieve`, then pass the result to the merge.

### M2. Log analytics: fallbacks removed

- **Where:** `backend/src/utils/log_parser.py:342`. The `try/except` was removed from `get_usage_analytics`, `get_chat_metrics` and the helpers. The read paths were narrowed to `(OSError, UnicodeDecodeError)`, but the inner loops (e.g. `_estimate_system_uptime`, line 667) do not catch `AttributeError`.
- **Scenario:** a valid JSON line in `app.log` that is not an object (e.g. `123`) makes `/admin/analytics/usage` return 500. Before, it returned 200 with default values. Reproduced: `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/analytics.py`.
- **Same pattern:** the fallback of `get_logs_summary` was removed (`backend/src/utils/logs_reader.py:304`).
- **Note:** the oracle only pins the top-level keys of these endpoints, so it does not see this.

### M3. Disk-usage probe

`backend/src/api/endpoints/health.py:137`: the per-directory handler is narrowed to `OSError`. A `TypeError` (path `None`) or a `ZeroDivisionError` now makes the whole probe `healthy: false` instead of filling in one entry.

### M4. FAISS fallbacks narrowed

- `faiss_store.py:135`: `_initialize_index` only falls back to an empty index on `VectorStoreException`.
- `faiss_store.py:698`: `load` does not wrap `ImportError` / `ModuleNotFoundError` from a legacy pickle. Such an error now makes the store's constructor raise. Before, it silently created an empty index, which the next persist then wrote over the old one. The new behaviour is arguably better, but it is a functional change and should be recorded as a decision.
- `faiss_store.py:933`: `_get_existing_document_ids` only catches `SQLAlchemyError`.
- `backend/src/services/index_maintenance.py:193`: `record_rebuild_failure` only catches `SQLAlchemyError`. Any other audit failure escapes the route's `except`. The response then becomes the generic `INTERNAL_ERROR`, with `str(exc)` outside production, instead of "Vector index rebuild failed".

### M5. Mistral client

- `_make_request` now only wraps `TimeoutError` and `ValueError` (plus `aiohttp.ClientError`). Other exceptions, such as a `TypeError` from JSON-encoding the payload or a `RuntimeError`, are no longer turned into `LLMAPIError`.
- The `embed` batching loop and `health_check` were narrowed to `LLMException`. `health_check` is not called anywhere.
- Low impact: the callers keep their boundaries.

### M6. JWT

`verify_token` is narrowed to `(PyJWTError, TypeError, ValueError)`. An unexpected exception would now propagate out of `JWTBearer` (500) instead of giving a 401. It still fails closed (no access granted). `verify_password` is still protected by the catch-all in `_authenticate_admin`.

### M7. Dead code left in place, and false documentation

- **`file_watcher`:** the module is wired nowhere (D2.8), yet `CLAUDE.md:43` ("Folder monitoring for auto-ingestion") and `README.md:102` still present it as a feature, and `watch_enabled=True` stays in `config.py`. The façade pass (8) corrected other false claims but kept this one.
- **Unused Pydantic models in `backend/src/shared/models.py`:** `DocumentUpdate`, `DocumentStatsResponse`, `ConfigurationCreate/Update/Response/ListResponse`, `AuditLogBase/Create/Response/ListResponse`, `DatabaseStatsResponse`. Their old heading "Models for future features" was renamed "Health check and error models" (`models.py:180`), which mislabels them.
- **Kept alive only by unit tests:** `chat._generate_cache_key`, `ChatResponse`, `SourceReference`.
- **Unused helpers:**
  - `lru_cache`: `get_or_set`, `invalidate_pattern`, `get_chat_response`, `set_chat_response`.
  - `monitoring.logger`: the `log_*` functions.
  - `password_utils`: `generate_secure_password`, `is_password_compromised`, `sanitize_password_error_message`.
  - `models`: `create_*_action`, `get_typed_value`.
- **Stale comments:** `processor.py:315` and `:415` still mention `BudgetExceededError` (now an alias kept for a frozen test, which is fine).
- **Stale docstring:** `admin.py:760` still advertises "Performance status assessment", although `get_performance_status` (dead code) was deleted.

### M8. The `pre-cleanup` tag was never pushed

See D0.1. Reviewers on GitHub cannot reproduce the diff base. The PR should name `b1e18e6` explicitly.

---

## Checked without findings

- **Routes and status codes:** the OpenAPI snapshot covers the contract. The router-level `require_admin` guards on `/admin` and `/documents` are kept, the read-only `reader_router` is unchanged, and the 403 from `JWTBearer.make_not_authenticated_error` is kept. Secret masking (`mask_secrets`, `MASKED_VALUE` filtering on PUT) is unchanged.
- **Typed responses (pass 4):**
  - Field names, order and types match the old dicts.
  - `CacheStats` covers every key of `get_stats()`.
  - `ModelUsageToday` and `DailyModelUsage` match the repository rows. They are exercised with data by the frozen test `tests/integration/test_admin_usage.py` (the oracle has `today_by_model: []`).
  - `VectorStoreOverview.health_status` is a bool, as `health_check()` returns.
  - Remaining effect: a float field fed an int is serialized as `0.0` instead of `0`, which is equivalent in JSON.
- **Merged upload (D3.4):** the order of checks, the messages and the admin/documents differences are kept: extension check, audit event, file removal on an unexpected error, prepared upload directory.
- **SSE stream and `ReservationSettlement`:** same events and same order. Settlement happens exactly once: cache hit, background task when the stream is never iterated, `finally` in the generator. The `aclosing()` around `_stream_answer` records the estimated usage before the outer `finally` settles, which is the same sequence as before.
- **RAG pipeline split into steps:**
  - prompt, context numbering, citations, cache write after `done`, and confidence: identical;
  - dense path: identical;
  - hybrid path: identical apart from M1.
- **Validator** (`validation_utils.py`): the split keeps the same checks, keys and order. The dead function `create_validation_report` was removed.
- **ORM models (SQLAlchemy 2.0):** the schema is unchanged (types, nullability, defaults, indexes, constraints). Chunking (`chunking.py`) has only formatting changes.
- **Exception handlers in `main.py`:** `MimirError` is sent to the existing general handler (same payload). `BudgetExceeded` is never raised by a route.
- **Dependencies:** the lockfiles use hashes. Moving `aiosqlite` to runtime is justified (the async engine is created eagerly). pytest 9 and pytest-asyncio 1.4: the suite runs green (1010 passed, 0 skipped; the 3 previously skipped tests were empty and were deleted).
- **Comments:** no French comments remain in `backend/src`.

## Reproduction scripts

They are in `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/`. Each one takes the `backend` path as its first argument:
- old tree: `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/review/pre/backend`
- new tree: `/home/user/mimir/backend`

Run them after `source /tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/testenv.sh`, with the cwd set to the scratchpad.

| Script | Finding |
|---|---|
| `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/bm25_drain.py` | B1 |
| `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/bm25_eof.py` then `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/bm25_getter.py` (the second also takes the index directory) | B2 |
| `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/pdf_page_error.py` | B3 |
| `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/analytics.py` | M2 |
| `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/loop_stall.py`, `/tmp/claude-0/-home-user/35bb50c3-d8b4-5f25-91bf-0238f8ffa833/scratchpad/t/loop_stall_rebuild.py` | M1 |

**Common thread in B1–B3, I1–I4 and M2–M6:** pass 2 narrowed `except` clauses that guarded a "best effort" or "never fail" contract. The oracle injects only exception types that are in the new lists, so it cannot detect these changes. The cheapest fix: treat these sites as boundaries (`except Exception` with a justified `noqa: BLE001`), restore the edited tests, then pass the quality gate again.
