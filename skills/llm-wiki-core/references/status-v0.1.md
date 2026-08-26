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
principal_not_found
principal_conflict
principal_contract_stale
principal_kind_unsupported
principal_role_unsupported
principal_domain_mismatch
capability_denied
mapping_owner_mismatch
operation_not_allowed
invalid_invocation
```

`ok` and `enabled` indicate successful command and binding states.
`already_exists` is a successful idempotent result. Missing, disabled, mismatch,
and unavailable states must follow the calling domain Skill's documented
fallback behavior. `scope_busy` means the caller may retry after the active
scope writer finishes. `partial_failure` means at least one requested Domain
export succeeded and at least one failed; it is not a successful overall state.
Validation, read, I/O, and unexpected errors must never be reported as a
successful write.

Principal-aware Runtime 0.3 Invocations additionally use the Principal,
capability, Mapping-owner, operation, and invalid-envelope statuses above.
`principal_contract_stale` requires an explicit contract refresh; it is never
an implicit authorization to continue. A Runtime 0.2 record that was already
complete remains readable. A pending approval created under the older contract
is stale and must be revalidated before it can cause a write.
