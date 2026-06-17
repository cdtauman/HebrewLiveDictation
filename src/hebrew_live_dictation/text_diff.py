from dataclasses import dataclass


@dataclass(frozen=True)
class RewritePlan:
    common_prefix: str
    chars_to_delete: int
    text_to_insert: str


def common_prefix(s1: str, s2: str) -> str:
    i = 0
    while i < len(s1) and i < len(s2) and s1[i] == s2[i]:
        i += 1
    return s1[:i]


def compute_end_rewrite(old_text: str, new_text: str) -> RewritePlan:
    prefix = common_prefix(old_text or "", new_text or "")
    return RewritePlan(
        common_prefix=prefix,
        chars_to_delete=len(old_text or "") - len(prefix),
        text_to_insert=(new_text or "")[len(prefix):],
    )
