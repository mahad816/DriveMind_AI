# Google credential diagnostic boundary

Credential storage and authorization behavior are unchanged. Encryption remains inactive.

Application error handlers return fixed messages, including in debug mode. Starlette debug traceback responses are disabled. Google provider errors are wrapped without printable provider exception chains. Classification uses SDK types and structured status/error codes, never token matching or exception-text parsing. Unknown failures remain unknown.

SQLAlchemy uses `hide_parameters=True` and `echo=False`. This hides bind parameters in standard statement logs/errors; it does not sanitize arbitrary driver messages, result rows under externally enabled DEBUG logging, or explicitly logged values. Do not enable SQL result debugging for credential operations.

New unexpected indexing-job errors contain an operation and bounded category. Existing status transitions and aggregate per-file failure counts remain unchanged. Background handlers log fixed diagnostics without traceback objects. Existing database job-error strings are not rewritten and may still contain sensitive historical details; inspect/clean them only in a separately approved operation.

Synthetic regression tests cover SQL diagnostics, OAuth and content responses, explicit/implicit refresh failures, token representations, and sync job serialization. Existing successful OAuth/Drive tests remain in the regression suite.

Limits: this is an application diagnostic boundary, not a system-wide log scrubber. Proxy/server access logs can contain OAuth callback query parameters. Third-party HTTP/SDK logging, server-level exception logging, external telemetry, historic logs and database backups require separate operational review. Do not log complete URLs, headers, provider bodies, settings dumps or SDK credential objects. No hosting/logging configuration was changed here.
