# Threat Model

## Identified Threats and Controls

| Threat | Control |
|--------|---------|
| SSRF | URL scheme allow-list, private IP blocking, localhost blocking |
| DNS Rebinding | IP validation at request time |
| Redirect abuse | Redirect target validation, cross-origin logging |
| Response size exhaustion | Max response size limit |
| Decompression bombs | Content size validation before processing |
| Unsafe filenames | UUID-based filenames, no URL-derived paths |
| Directory traversal | Path resolution checks |
| SQL Injection | SQLAlchemy ORM, parameterized queries |
| API pagination abuse | Bounded pagination (max 100) |
| Excessive concurrency | Global semaphore limit |
| Sensitive header logging | Explicit exclusion of auth/cookie headers |
| Information disclosure | Raw content never exposed via API |

## Production Hardening
- Reject http:// (only https://)
- Reject all private RFC1918 ranges
- Reject link-local and metadata addresses
- Structured logs never contain raw page content
