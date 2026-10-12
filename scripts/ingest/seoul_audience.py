"""Collection-only audience labels from USETGTINFO; never infer from body text."""
from dataclasses import dataclass

ALLOWED_AUDIENCES = frozenset({'제한없음', '성인', '청년'})


@dataclass(frozen=True)
class CollectionAudience:
    selected: bool
    reason: str
    labels: tuple[str, ...] = ()


def collection_audience(value: object) -> CollectionAudience:
    if value is None or isinstance(value, str) and not value.strip():
        return CollectionAudience(False, 'audience_missing')
    if not isinstance(value, str):
        return CollectionAudience(False, 'audience_unrecognized')
    # The API flattens labels and optional conditions into one string. Split
    # separators only outside balanced parentheses, preserving the source value.
    pairs = {'(': ')', '（': '）'}
    stack, parts, part = [], [], []
    for char in value.strip():
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                return CollectionAudience(False, 'audience_unrecognized')
        if char in ',，·ㆍ/、' and not stack:
            parts.append(''.join(part).strip())
            part = []
        else:
            part.append(char)
    if stack:
        return CollectionAudience(False, 'audience_unrecognized')
    parts.append(''.join(part).strip())
    labels = []
    for entry in parts:
        # A label is complete: 성인만/미성인/성인 보호자 are not 성인.
        opening = next((i for i, char in enumerate(entry) if char in pairs), len(entry))
        label = entry[:opening].strip()
        if not label:
            return CollectionAudience(False, 'audience_unrecognized')
        depth = 0
        for char in entry[opening:]:
            if char in pairs:
                depth += 1
            elif char in pairs.values():
                depth -= 1
            elif depth == 0 and not char.isspace():
                return CollectionAudience(False, 'audience_unrecognized')
        labels.append(label)
    labels = tuple(labels)
    if ALLOWED_AUDIENCES.intersection(labels):
        return CollectionAudience(True, 'audience_selected', labels)
    return CollectionAudience(False, 'audience_not_selected', labels)
