# Progress Log

## 2026-03-13

### Sentinel token resilience for transient `oai-did` 403 errors
- Added retry-with-backoff behavior for `_fetch_oai_did` on HTTP 403, including jitter and delayed terminal raise after retry exhaustion.
- Added IPRoyal session rotation support in retry paths so repeated `oai-did` fetches can use a fresh exit IP.
- Reused cached `_cached_device_id` in cached sentinel token generation so repeated token generation can skip redundant `oai-did` fetches.
- Added delayed re-raise behavior for sentinel 403s in `generate_video` to support outer retry orchestration.
- Updated generation-level retry policy to explicitly treat sentinel `oai-did` 403 as retryable.
- Added `ProxyManager.get_proxy_url_rotated` utility for safe URL-based IPRoyal session rotation.

### Validation snapshot
- `python -m compileall src/services/sora_client.py src/services/generation_handler.py src/services/proxy_manager.py`

### Post-review cleanup for sentinel resilience implementation
- Removed unused `ProxyManager.get_proxy_url_rotated` dead code and corresponding unused imports from `proxy_manager.py`.
- Updated `_rotate_proxy_session` to strip any trailing `_session-<hex>` suffix before applying a new suffix, preventing session suffix accumulation across retries.
- Updated `_invalidate_sentinel_cache` to also clear `_cached_device_id` and log device-id-inclusive cache invalidation.

## 2026-03-14

### nf/create invalid request handling hardening
- Updated generation retry classification to mark Sora upstream `invalid_request` signatures as non-retryable and emit a classifier log for operational clarity.
- Hardened `_nf_create_urllib` cookie diagnostics to clearly indicate whether session cookie context came from POW cookie header, token `st`, or neither (without leaking sensitive cookie/token values).
- Updated nf/create payload builders to omit optional `style_id` when `None`/empty, preventing `"style_id": null` from being sent upstream.

### Validation snapshot
- `python -m compileall src/services/generation_handler.py src/services/sora_client.py src/services/load_balancer.py`
