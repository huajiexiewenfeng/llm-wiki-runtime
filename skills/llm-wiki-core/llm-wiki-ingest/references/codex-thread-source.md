# Codex Thread Source Adapter

Use this adapter only after the user names or asks to find an old Codex task.

## Acquire

1. Call `list_threads` with the user-provided title or keywords.
2. Show every plausible title, date, and `thread_id`. Even with one result, ask
   the user to confirm the exact task before reading its full content.
3. Call paginated `read_thread` until all pages are available. Preserve
   oldest-to-newest turn and item order.
4. Represent each text item with stable `thread_id`, `turn_id`, `item_id`,
   `turn_order`, `item_order`, and the unmodified text.

## Select

The model may propose evidence, but each selection is an exact character range:
`turn_id`, `item_id`, `start`, and `end`. Preview the verbatim slice. A message
mixing JD and candidate material is skipped by default; continue only after the
user confirms a precise JD-only range. Never persist the complete task merely to
extract one record.

After confirmation, `prepare-excerpt` calculates the original-message checksum,
sorts selections oldest-to-newest, creates the evidence snapshot, and returns
controlled provenance for `copy-source`.

## Host Fallback

When `list_threads` or `read_thread` is unavailable, ask the user for a
Markdown or JSON export and process that file through the same preview Gate.
Do not claim that a task was read when the host tool was unavailable or pagination was
incomplete.
