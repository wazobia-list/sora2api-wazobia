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
