"""Lead review regressions for S2-A (CR-S2A-L01)."""

from toolbox_backend.domain.settings import Library
from toolbox_backend.services.work_items import MediaRegistry

LIB = Library(id="lib:a", name="A", base_url="https://ado.example.test/tfs")
URL = "https://ado.example.test/tfs/C/_apis/wit/attachments/abc?fileName=x.svg"


def test_same_url_inline_image_and_attachment_get_distinct_kinds():
    registry = MediaRegistry()
    image_id, _ = registry.register("proj:1", LIB, URL, "image", "x.svg")
    attachment_id, _ = registry.register("proj:1", LIB, URL, "attachment", "x.svg")
    assert image_id != attachment_id
    assert registry.get(image_id).kind == "image"
    assert registry.get(attachment_id).kind == "attachment"
    # Same (url, kind) still deduplicates.
    assert registry.register("proj:1", LIB, URL, "attachment", "x.svg")[0] == attachment_id


def test_encoded_separator_check_applies_to_path_not_query():
    """CR-S2D-L01: %2F/%5C/%2E are rejected in the raw path only, not in the query."""
    from toolbox_backend.adapters.ado_read import within

    ok = "https://ado.example.test/tfs/C/_apis/wit/attachments/abc?fileName=a%2Epng%2Fb"
    assert within(LIB, ok)
    assert not within(LIB, "https://ado.example.test/tfs/C/_apis/wit/attachments/a%2Fb")
    assert not within(LIB, "https://ado.example.test/tf%73/C/x.png")
