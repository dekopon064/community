"""REST 페이지 checkpoint는 connector 내부에만 둔다."""

from __future__ import annotations

from ingest.models import Checkpoint

START_PAGE = 1


def page_from_checkpoint(checkpoint: Checkpoint | None) -> int:
    if checkpoint is None:
        return START_PAGE
    page = checkpoint.rest_page_num()
    if page is None or page < START_PAGE:
        return START_PAGE
    return page


def next_page_checkpoint(page_num: int) -> Checkpoint:
    return Checkpoint.for_rest_page(page_num + 1)
