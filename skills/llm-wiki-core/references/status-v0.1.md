# LLM Wiki Runtime Status Vocabulary v0.1

Generic Skills and CLI envelopes use this Phase 1 vocabulary:

```text
ok
enabled
missing_config
disabled
profile_mismatch
domain_mapping_required
already_exists
validation_error
scope_busy
partial_failure
read_denied
runtime_unavailable
io_error
unexpected_error
```

`ok` and `enabled` indicate successful command and binding states.
`already_exists` is a successful idempotent result. Missing, disabled, mismatch,
and unavailable states must follow the calling domain Skill's documented
fallback behavior. `scope_busy` means the caller may retry after the active
scope writer finishes. `partial_failure` means at least one requested Domain
export succeeded and at least one failed; it is not a successful overall state.
Validation, read, I/O, and unexpected errors must never be reported as a
successful write.
