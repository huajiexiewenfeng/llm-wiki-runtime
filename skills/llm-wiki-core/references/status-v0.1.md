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
read_denied
runtime_unavailable
io_error
unexpected_error
```

`ok` and `enabled` indicate successful command and binding states.
`already_exists` is a successful idempotent result. Missing, disabled, mismatch,
and unavailable states must follow the calling domain Skill's documented
fallback behavior. Validation, read, I/O, and unexpected errors must never be
reported as a successful write.
