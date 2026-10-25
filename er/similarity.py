"""Score how alike two organization names are, and whether their addresses agree."""

from __future__ import annotations

from difflib import SequenceMatcher

from er.normalize import address_tokens, tokens


def _token_match(a: str, b: str) -> bool:
    """Equal, or one is a prefix of the other when the shorter has at least four letters ("tech", "technologies")."""
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and long.startswith(short)


def token_overlap(a: list[str], b: list[str]) -> float:
    """Shared tokens over all tokens, counting a prefix match as shared."""
    if not a or not b:
        return 0.0
    left, right = list(a), list(b)
    shared = 0
    for t in left:
        for i, u in enumerate(right):
            if _token_match(t, u):
                shared += 1
                del right[i]
                break
    return shared / (len(a) + len(b) - shared)


def name_score(a: str, b: str) -> float:
    """Half token overlap, half character similarity of the names with spaces removed."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    # SequenceMatcher and the greedy token pairing both depend on argument order, so fix the order.
    ta, tb = sorted((ta, tb))
    sequence = SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    return round(0.5 * token_overlap(ta, tb) + 0.5 * sequence, 4)


def address_relation(a: str | None, b: str | None) -> str:
    """ "agree", "conflict", or "unknown". Conflict means both addresses exist and share no place word."""
    ta, tb = address_tokens(a), address_tokens(b)
    if not ta or not tb:
        return "unknown"
    shared = ta & tb
    if len(shared) / len(ta | tb) >= 0.5:
        return "agree"
    return "conflict" if not shared else "unknown"
