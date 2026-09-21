"""atchFile를 파싱 직후 제거하고 메타만 남긴다. 값은 로그·해시·저장에 넣지 않는다.

계약: 최상위와 중첩 객체의 atchFile/atch_file/atchFileName을 재귀적으로 제거한다.
원본 dict는 변이하지 않는다. 허용 메타데이터는 attachment_present, 길이, data URL 여부뿐이다.
"""

from __future__ import annotations

from typing import Any, NamedTuple

FORBIDDEN_ATTACHMENT_KEYS = frozenset({"atchfile", "atch_file", "atchfilename"})
ALLOWED_ATTACHMENT_META_KEYS = frozenset(
    {"attachment_present", "attachment_length", "is_data_url"}
)


class AttachmentMeta(NamedTuple):
    present: bool
    length: int
    is_data_url: bool


def _is_forbidden_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    compact = key.replace("-", "").replace(" ", "")
    return compact.lower() in FORBIDDEN_ATTACHMENT_KEYS


def drop_forbidden_attachments(value: Any) -> tuple[Any, AttachmentMeta]:
    """중첩 구조에서 첨부 키를 제거하고 메타를 합산한다. 원본 값은 버린다."""
    present = False
    length = 0
    is_data_url = False

    def walk(node: Any) -> Any:
        nonlocal present, length, is_data_url
        if isinstance(node, dict):
            cleaned: dict[str, Any] = {}
            for key, child in node.items():
                if _is_forbidden_key(key):
                    present = True
                    if isinstance(child, str):
                        length += len(child)
                        if child.lstrip().lower().startswith("data:"):
                            is_data_url = True
                    elif child is not None:
                        length += len(str(type(child)))
                    continue
                cleaned[key] = walk(child)
            return cleaned
        if isinstance(node, list):
            return [walk(child) for child in node]
        return node

    return walk(value), AttachmentMeta(present, length, is_data_url)


def contains_forbidden_attachment_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_forbidden_key(key) or contains_forbidden_attachment_key(child):
                return True
        return False
    if isinstance(value, list):
        return any(contains_forbidden_attachment_key(child) for child in value)
    return False


def merge_attachment_meta(item: dict[str, Any], scanned: AttachmentMeta) -> AttachmentMeta:
    length_raw = item.get("attachment_length")
    try:
        declared_length = int(length_raw) if length_raw is not None else 0
    except (TypeError, ValueError):
        declared_length = 0
    return AttachmentMeta(
        present=bool(item.get("attachment_present")) or scanned.present,
        length=max(declared_length, scanned.length),
        is_data_url=bool(item.get("is_data_url")) or scanned.is_data_url,
    )


def strip_attachment_meta_keys(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in ALLOWED_ATTACHMENT_META_KEYS
    }


def sanitize_source_item_copy(item: dict[str, Any]) -> dict[str, Any]:
    """원본을 복사한 뒤 첨부를 제거하고 허용 메타만 남긴다."""
    cleaned, meta = drop_forbidden_attachments(item)
    if not isinstance(cleaned, dict):
        cleaned = {}
    merged = merge_attachment_meta(cleaned, meta)
    cleaned["attachment_present"] = merged.present
    cleaned["attachment_length"] = merged.length
    cleaned["is_data_url"] = merged.is_data_url
    return cleaned


def extract_sanitized_source_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise RuntimeError("source_list_invalid")
    return [
        sanitize_source_item_copy(item)
        for item in items
        if isinstance(item, dict)
    ]
