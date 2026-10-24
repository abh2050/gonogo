from ingest import ntrs, t2_portal

DETAIL = """
<span class="category">Mechanical and Fluid Systems</span>
<span class="case_number">LEW-20196-1</span>
<span class="patent_number"><a href="x">11,912,078</a></span>
<p>The technology is at TRL 4 (component validation).</p>
"""


def test_parse_detail_reads_labeled_spans() -> None:
    d = t2_portal.parse_detail(DETAIL)
    assert d["case_numbers"] == ["LEW-20196-1"]
    assert d["patent_numbers"] == ["11912078"]
    assert d["detail_category"] == "Mechanical and Fluid Systems"
    assert d["trl"] == 4


def test_parse_search_row_strips_highlight_markup() -> None:
    row = [
        "LEW-TOPS-161",
        "LEW-TOPS-161",
        '<span class="highlight">Shape</span> Memory',
        "abs",
        "",
        "Sensors",
        "",
        "",
        "",
        "GRC",
        "",
        "",
        1.0,
    ]
    rec = t2_portal.parse_search_row(row)
    assert rec["title"] == "Shape Memory" and rec["category"] == "Sensors" and rec["center_code"] == "GRC"


def test_ntrs_relevance_filter_needs_shared_terms() -> None:
    hits = ntrs.relevant_hits(
        "Shape Memory Alloy Tubular Structure",
        [{"id": 1, "title": "Shape memory alloy spring tire"}, {"id": 2, "title": "Unrelated rocket report"}],
    )
    assert [h["id"] for h in hits] == [1]


def test_ntrs_pdf_link_prefers_pdf_rendition() -> None:
    files = [{"mimetype": "application/vnd.ms-powerpoint", "links": {"original": "/a.pptx", "pdf": "/a.pdf"}}]
    assert ntrs.pdf_link(files) == "/a.pdf"
    assert ntrs.pdf_link([{"mimetype": "text/plain", "links": {"original": "/a.txt"}}]) is None


def test_ntrs_query_is_independent_of_set_order() -> None:
    body = ntrs.search_body("Sensor Sensors Array for Sensing")
    assert body["q"] == "sensor sensors array sensing"
