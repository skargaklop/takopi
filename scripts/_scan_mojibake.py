"""Scan takopi prompt-batch files for mojibake (broken UTF-8 dash etc.)."""

from __future__ import annotations

import pathlib
import re

TARGETS = [
    pathlib.Path("src/takopi/telegram/prompt_batch.py"),
    pathlib.Path("docs/how-to/long-telegram-prompts.md"),
    pathlib.Path("docs/reference/config.md"),
    pathlib.Path("docs/reference/transports/telegram.md"),
    pathlib.Path("docs/reference/commands-and-directives.md"),
]

# Classic mojibake sequences for an em dash / smart quotes read as cp1251,
# plus the Unicode replacement character.
MOJIBAKE_RE = re.compile("[\ufffd\u0402\u2014\u2013\u201c\u201d]")

for path in TARGETS:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"{path}: UTF-8 DECODE ERROR at {exc}")
        continue
    found = []
    for match in MOJIBAKE_RE.finditer(text):
        start = max(0, match.start() - 30)
        end = min(len(text), match.end() + 30)
        found.append((match.group(0), text[start:end].replace("\n", "\\n")))
    if found:
        for char, ctx in found:
            print(f"{path}: mojibake {char!r} in ...{ctx}...")
    else:
        print(f"{path}: clean")
