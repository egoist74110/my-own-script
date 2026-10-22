"""Bounded line framing: no raw prefix is emitted until a whole line can be redacted."""

import re

from toolbox_backend.logging_setup import redact_exception


def safe_text(text):
    text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))", "", text)
    text = "".join(c for c in text if c in "\t\n" or ord(c) >= 32 and ord(c) != 127)
    text = redact_exception(text)
    text = re.sub(r"(?i)\b(?:basic|bearer)\s+[^\s]+", "***", text)
    text = re.sub(r"(?i)(?:https?|ssh)://[^\s/@]+@", "[redacted]@", text)
    text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))", "", text)
    return "".join(c for c in text if c in "\t\n" or ord(c) >= 32 and ord(c) != 127)


class StreamRedactor:
    def __init__(self, limit=8192):
        self.limit = limit
        self.pending = bytearray()
        self.dropping = False

    def feed(self, block):
        output = []
        for part in block.splitlines(keepends=True):
            ended = part.endswith((b"\n", b"\r"))
            if not self.dropping:
                if len(self.pending) + len(part) > self.limit:
                    self.pending.clear()
                    self.dropping = True
                    output.append("省略过长日志行\n")
                else:
                    self.pending.extend(part)
            if ended:
                if not self.dropping:
                    output.append(safe_text(self.pending.decode(errors="replace")))
                self.pending.clear()
                self.dropping = False
        return output

    def finish(self):
        result = [] if self.dropping else [safe_text(self.pending.decode(errors="replace"))]
        self.pending.clear()
        self.dropping = False
        return [x for x in result if x]
