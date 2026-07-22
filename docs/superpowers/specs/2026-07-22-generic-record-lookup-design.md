# Generic Record Lookup and Domain Identity Resolution Design

Date: 2026-07-22
Status: Proposed for implementation
Repositories: `llm-wiki-runtime`, `role-copilot-skills`

## 1. Context

LLM Wiki queries currently require the caller to know a record path before calling `load-context-pack`. Human requests commonly identify an entity by a display name instead of a path or stable ID. The HR failure that exposed this gap involved a candidate whose record path used an opaque `candidate_id` and whose Markdown body contained PDF extraction control characters. A filesystem text search returned no result even though the record and graph node existed.

This is not an HR-only problem. Any Domain may need to resolve a human-facing value to a durable record: a project name to a project record, a package name to a release record, a course title to a learning record, or a customer label to an account record.

The solution must not make the runtime understand HR semantics, and it must not make an HR Skill depend on graph output, filesystem traversal, or runtime internals.

## 2. Architectural Principles

1. Runtime owns deterministic access, validation, authorization, and generic record matching.
2. Domain packages own record meaning, identity fields, display fields, aliases, and ambiguity handling.
3. SCP owns cross-Skill data contracts and authorization declarations; it does not implement record search.
4. Graph output is derived presentation data and is never the canonical query index.
5. Original sources remain outside ordinary context packs and record lookup results.
6. Runtime never performs fuzzy business inference or silently chooses among multiple matches.
7. Installed Skill directories are deployment targets, not source repositories.

## 3. Goals

- Resolve a human-provided scalar value to one or more records without knowing their paths.
- Keep the lookup mechanism reusable across all Domains.
- Let each Domain declaratively define record identity and lookup fields.
- Return only a profile-controlled metadata allowlist and scope-relative paths.
- Preserve deterministic ordering and authorization behavior.
- Prevent malformed extracted text from entering future Markdown records.
- Give HR Skills a stable candidate-resolution workflow that remains useful when LLM Wiki is disabled.

## 4. Non-Goals

- Full-text search over Markdown bodies.
- Fuzzy name matching, phonetic matching, embeddings, ranking, or LLM inference.
- Using `graph.json` as a record index.
- Building a persistent database or search service in this phase.
- Adding HR concepts to runtime code, CLI arguments, models, errors, or tests.
- Moving candidate identity semantics into SCP v0.1.
- Automatically merging duplicate records.

## 5. Options Considered

### 5.1 Caller-Supplied Field Names

The caller passes lookup fields such as `display_name` and `aliases` to the runtime command.

This is simple but makes every Skill understand runtime query syntax and repeat field allowlists. It also makes privacy behavior depend on each invocation. This option is rejected as the primary design.

### 5.2 Declarative Lookup Rules in the Domain Profile

The active Domain profile declares how each record type can be found and which metadata may be returned. Runtime executes the generic declaration.

This preserves ownership boundaries, supports other Domains without code changes, and centralizes privacy defaults. This is the selected design.

### 5.3 Querying Graph Output

The caller reads `.llm-wiki/.meta/graph/<domain>/graph.json` and searches node labels.

This is fast when the graph is current, but graph export is optional, derived, and may be missing or stale. It also couples core query behavior to visualization. This option is rejected.

## 6. Domain Profile Contract

The active profile gains an optional `read_rules.record_lookup` mapping:

```yaml
read_rules:
  context_pack:
    include: [domains/hr/**]
    exclude: [sources/originals/**, .meta/**]
    max_files: 30
    max_chars_per_file: 4000

  record_lookup:
    candidate_profile:
      identity_field: candidate_id
      display_field: display_name
      match_fields: [display_name, aliases]
      return_fields:
        - candidate_id
        - display_name
        - aliases
        - current_resume_version_id
      max_results: 20
```

The example is HR-owned configuration included to show one consumer. Runtime implementation and repository tests use neutral record types and understand only the generic keys.

### 6.1 Validation Rules

- A lookup record type must also exist in `write_rules.records`.
- `identity_field`, `display_field`, every `match_fields` value, and every `return_fields` value must use the existing conservative frontmatter field-name syntax.
- `match_fields` must contain at least one unique field name.
- `return_fields` must contain `identity_field` and `display_field`.
- `max_results` must be an integer from 1 through 100 and defaults to 20.
- Unknown keys fail profile validation.
- A profile without `record_lookup` remains valid and preserves current behavior.

## 7. Runtime Command

Add a flat CLI command consistent with current command naming:

```powershell
llm-wiki find-records `
  --scope-root "C:\path\to\scope" `
  --record-type candidate_profile `
  --lookup-value-json '"Example Candidate"' `
  --caller-domain hr `
  --target-domain hr
```

The command also accepts the same optional authorization inputs as `load-context-pack`:

- `--domain-policies-json`
- `--caller-groups-json`

`--lookup-value-json` must decode to a non-null scalar string, integer, finite float, or boolean. This avoids string-versus-number ambiguity while reusing the runtime's existing JSON CLI convention. Null is rejected because it is not a usable record identity and could unintentionally match many incomplete records.

### 7.1 Output

Unique result:

```json
{
  "status": "found",
  "record_type": "candidate_profile",
  "lookup_value": "Example Candidate",
  "matches": [
    {
      "path": "domains/hr/candidates/candidate-example-001/profile.md",
      "checksum": "sha256:...",
      "identity": "candidate-example-001",
      "display": "Example Candidate",
      "fields": {
        "candidate_id": "candidate-example-001",
        "display_name": "Example Candidate",
        "aliases": []
      }
    }
  ],
  "context_refs": [
    {
      "path": "domains/hr/candidates/candidate-example-001/profile.md",
      "checksum": "sha256:..."
    }
  ],
  "warnings": []
}
```

Other successful application statuses are:

- `not_found`: no matching record; `matches` is empty.
- `multiple_matches`: more than one matching record; runtime returns up to `max_results` and never selects one.

Every successful response includes `truncated`, which is `true` only when matching records exceed `max_results`. These statuses are not runtime failures and use exit code 0. Configuration, authorization, and I/O failures retain the runtime's existing error categories and nonzero exit behavior.

### 7.2 Matching Semantics

1. Load the active profile snapshot from `scope_root`.
2. Authorize the caller and target Domain with the same policy mechanism used by context packs.
3. Find the requested record lookup declaration.
4. Enumerate only files allowed by `read_rules.context_pack.include` and `exclude`.
5. Parse leading frontmatter only; do not search or return Markdown bodies.
6. Require frontmatter `record_type` to equal the requested record type.
7. Compare the lookup value against every declared `match_fields` field using OR semantics.
8. Scalar fields match by scalar equality after Unicode NFC normalization for strings.
9. List fields match when any scalar member equals the lookup value.
10. String comparison is case-sensitive and does not perform substring or fuzzy matching.
11. Sort matches by scope-relative POSIX path.
12. Return only `return_fields`, the relative path, checksum, derived `identity`, and derived `display`.

Leading and trailing whitespace remains significant in stored frontmatter. Callers may normalize user input according to Domain semantics before invoking runtime; runtime does not silently alter stored identity values.

### 7.3 Frontmatter Scanning

Record discovery reads a bounded leading region sufficient for frontmatter, with a default maximum of 64 KiB per file. A missing closing delimiter, invalid frontmatter, or oversized frontmatter causes that record to be skipped with a stable warning code and relative path. One malformed record does not make all lookup results unavailable.

The scanner must not depend on `rg`, filesystem filename conventions, graph export, or source registries.

## 8. Runtime API

Introduce focused generic units:

```python
@dataclass(frozen=True)
class RecordLookupRule:
    record_type: str
    identity_field: str
    display_field: str
    match_fields: tuple[str, ...]
    return_fields: tuple[str, ...]
    max_results: int = 20


def find_records(
    scope_root: Path,
    record_type: str,
    lookup_value: FrontmatterScalar,
    *,
    caller_domain: str | None = None,
    target_domain: str | None = None,
    domain_policies: dict | None = None,
    caller_groups: list[str] | None = None,
) -> dict:
    ...
```

Profile parsing owns declaration validation. A dedicated record-lookup module owns frontmatter enumeration and matching. CLI orchestration must not be added to `graph_collect.py` or reuse graph models.

## 9. Authorization and Privacy

- Lookup uses the active profile's read allowlist and forced `.meta/**` exclusion.
- `sources/originals/**` remains excluded by profile policy.
- Cross-Domain lookup follows the same readable-by and caller-group checks as context packs.
- Result fields are profile allowlisted; runtime never returns all frontmatter by default.
- Warnings contain stable reason codes and relative paths, not raw frontmatter or exception text.
- Lookup events may be audited using command, status, record type, result count, and duration. Lookup values and returned personal metadata must not be written to the audit log.

## 10. Record Text Hygiene

### 10.1 Runtime Boundary

`write-record` validates Markdown record content before acquiring the scope lock or changing any file. It permits tab, line feed, and carriage return. It rejects other C0 control characters and DEL, including NUL, with a stable validation error.

Runtime does not silently strip these characters because silent mutation would change source-backed content without Domain awareness. `copy-source` remains byte-preserving and is unaffected.

### 10.2 Domain Ingest Boundary

Domain extraction code may sanitize extracted text before composing a Markdown record. HR PDF extraction will remove forbidden control characters, retain ordinary Unicode text, and record a warning count in extraction metadata.

This responsibility is not HR-specific at the runtime level: every Domain must provide valid text to `write-record`, and runtime enforces the invariant uniformly.

### 10.3 Existing Data

Existing HR records containing forbidden controls receive a one-time local migration through runtime-controlled writes. The migration:

- creates a local backup outside the repository;
- removes only forbidden control characters;
- preserves frontmatter, normal text, provenance references, and line structure;
- records normal update checksums and change-log events;
- never commits or uploads candidate records.

## 11. HR Domain Behavior

HR candidate resolution uses Domain semantics independent of runtime implementation details:

1. If `candidate_id` is already known, load the exact authorized candidate record.
2. If only a human name or confirmed alias is available, resolve it using the candidate profile's declared lookup semantics.
3. On one result, load that exact record with `load-context-pack`.
4. On multiple results, ask one short disambiguation question using only approved non-contact fields.
5. On no result, check the user-provided or configured resume inputs before stating that no candidate material exists.
6. Never infer identity from a graph node, filename, company name, or approximate string match.
7. Confirmed aliases may be written to the Domain-owned `aliases` frontmatter list through the normal candidate-profile update flow.

The HR child Skills remain usable without LLM Wiki. When runtime is disabled or unavailable, they use their existing resume/JD inputs and state once that Wiki context was not applied.

## 12. SCP Boundary

SCP v0.1 does not change in this phase.

`query.primary_domain`, trust policy, and supporting-domain authorization remain SCP responsibilities. Record lookup declarations remain in the Domain profile because they describe records inside one Domain, not products exchanged between Skills.

A future SCP version may reference named Domain identities if cross-Skill entity handoff requires it. That extension is outside this design.

## 13. Source Repository and Installation Discipline

Implementation spans two source repositories:

- `llm-wiki-runtime`: generic profile schema, lookup API/CLI, content validation, core query Skill documentation, and generic tests.
- `role-copilot-skills`: HR profile declaration, HR resolution workflow, PDF extraction cleanup, and HR contract tests.

The currently installed HR package contains LLM Wiki integration files that are not present in the checked-out `role-copilot-skills` main branch. Before modifying HR behavior, implementation must establish a clean source-of-truth worktree, reconcile the installed integration files into source control without copying local candidate data, and then reinstall from that source. The installed package must not be edited as the only durable change.

Each repository receives separate local commits. No implementation step pushes to GitHub unless explicitly requested.

## 14. Compatibility and Rollout

1. Profiles without `read_rules.record_lookup` continue to parse and operate unchanged.
2. Existing `load-context-pack` behavior and output stay unchanged.
3. Graph export remains independent and optional.
4. Add runtime lookup and tests first.
5. Add the generic core query workflow that uses lookup before context loading.
6. Add HR profile semantics and HR workflow tests.
7. Clean existing HR records locally.
8. Reinstall HR Skills from the source repository.
9. Run end-to-end candidate-name queries with graph output absent to prove no graph dependency.

## 15. Test Strategy

### 15.1 Runtime Tests

Runtime fixtures use neutral record types such as `project_record` and `package_record`; they do not contain HR terminology.

Required cases:

- exact scalar match;
- list-member alias match;
- Unicode NFC-equivalent string match;
- case-sensitive non-match;
- no match, one match, and multiple matches;
- stable path ordering;
- result field allowlist;
- result limit and truncation marker;
- missing lookup declaration;
- invalid lookup profile fields;
- invalid and oversized frontmatter warnings;
- body containing NUL does not affect frontmatter-only lookup of legacy data;
- future `write-record` rejects forbidden controls without changing the target;
- tab, line feed, and carriage return remain valid;
- graph directory absent or stale has no effect;
- read-denied policy returns no record metadata;
- output and audit events omit lookup values and private metadata.

### 15.2 HR Skill Tests

- a candidate can be resolved when the user supplies only `display_name`;
- a confirmed alias resolves to the same candidate;
- duplicate display names require disambiguation;
- `not_found` triggers resume-input fallback before a missing-candidate claim;
- known `candidate_id` bypasses name resolution;
- child Skills do not search `graph.json`, run `rg`, or depend on candidate directory names;
- HR remains functional when runtime is disabled;
- PDF extraction removes forbidden controls and reports the count;
- no test fixture contains real candidate data.

### 15.3 End-to-End Acceptance

Using synthetic records only in repository tests:

1. Initialize a generic scope with a lookup-enabled profile.
2. Write two records sharing a display value and one record with an alias.
3. Verify `multiple_matches`, alias `found`, and context loading by returned path.
4. Remove graph output and repeat successfully.
5. Attempt to write a record containing NUL and verify no file change.

Local HR acceptance may use the private scope but stores no output in either repository.

## 16. Acceptance Criteria

- A Domain can declare lookup semantics without runtime code changes.
- Runtime code and tests contain no HR-specific identifiers or branching.
- HR Skills contain no graph-path, candidate-directory traversal, or shell-search dependency.
- A human candidate name deterministically resolves to zero, one, or multiple records.
- Multiple matches are never silently collapsed.
- Lookup returns only allowlisted fields and authorized context references.
- Future Markdown records cannot contain forbidden control characters.
- Existing HR data is cleaned locally without entering Git.
- Runtime and HR repositories pass their full test suites independently.
- Candidate lookup succeeds when graph export is missing.
