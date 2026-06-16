"""Remove rodapés genéricos das respostas do VigIA."""

from __future__ import annotations

import re

_BOILERPLATE_TRAILERS = (
    re.compile(
        r"(?:\n\n|\.\s+)Esse número representa[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Esse indicador (?:representa|mostra|reflete)[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Isso (?:representa|corresponde|indica)[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Isso significa que[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Este(?:s)? número[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)Ess(?:a|as|es) (?:família|famílias|dado|valor)[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)(?:Em resumo|Portanto|Dessa forma)[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
    re.compile(
        r"(?:\n\n|\.\s+)[^.!?]*transferência de renda[^.!?]*[.!?]?\s*$",
        re.I | re.S,
    ),
)


def trim_answer_boilerplate(answer: str) -> str:
    text = answer.strip()
    for _ in range(5):
        prev = text
        for pat in _BOILERPLATE_TRAILERS:
            text = pat.sub("", text).strip()
        if text == prev:
            break
    return re.sub(r"\n{3,}", "\n\n", text).strip()
