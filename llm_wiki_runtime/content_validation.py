from __future__ import annotations


_ALLOWED_C0 = {"\t", "\n", "\r"}


def validate_record_text(text: str) -> None:
    for character in text:
        codepoint = ord(character)
        if (codepoint < 0x20 and character not in _ALLOWED_C0) or codepoint == 0x7F:
            raise ValueError(
                f"record content contains forbidden control character U+{codepoint:04X}"
            )
