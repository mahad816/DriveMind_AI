"""Header, footer and page-number rules, tested on plain data (no PDF files needed).

Pages are described as ``(y, x, text)`` fragments on a 800-point-high page: the top band starts at
y >= 736 and the bottom band ends at y <= 64.
"""

from __future__ import annotations

from app.ingestion.extractors.pdf_furniture import (
    band_lines,
    furniture_keys,
    is_page_number,
    line_key,
    remove_furniture,
)

HEIGHT = 800.0


def bands_of(*fragments):
    return band_lines(list(fragments), bottom=0.0, height=HEIGHT)


def header_pages(count, header="ACME REPORT 2025", number_format="{}"):
    """``count`` pages whose bands hold a header and a page number."""
    return [
        bands_of((780, 50, header), (30, 300, number_format.format(n)), (400, 100, "body"))
        for n in range(1, count + 1)
    ]


# ---- keys ----------------------------------------------------------------------------------------------


def test_line_key_ignores_digits_spacing_and_case():
    assert line_key("Page 3 of 12") == line_key("PAGE 41 OF 7") == "page#of#"
    assert line_key("A  B") == line_key("ab")


def test_bare_page_numbers_are_recognised_but_real_text_is_not():
    for text in ("3", "Page 3", "page 3 of 12", "3 / 12", "- 3 -", "(3)", "[3]", "Page 12 of 12"):
        assert is_page_number(line_key(text)), text
    for text in ("Chapter 3", "3 apples", "Table 3", "Section 3.1", "ACME"):
        assert not is_page_number(line_key(text)), text


# ---- bands ---------------------------------------------------------------------------------------------


def test_only_text_in_the_top_and_bottom_band_is_a_band_line():
    result = bands_of((790, 50, "header"), (400, 50, "body"), (20, 50, "footer"))
    assert [line.text for line in result] == ["header", "footer"]


def test_fragments_on_the_same_baseline_form_one_line_left_to_right():
    result = bands_of((780, 400, "right part"), (780.5, 50, "left part"), (30, 10, "  "))
    assert [line.text for line in result] == ["left part right part"]


def test_a_page_of_no_height_has_no_bands():
    assert band_lines([(10, 10, "x")], bottom=0.0, height=0.0) == []


# ---- which keys are furniture -------------------------------------------------------------------------


def test_a_line_in_the_bands_of_40_percent_of_pages_repeats():
    pages = header_pages(5)
    repeating, numbers = furniture_keys(pages)
    assert line_key("ACME REPORT 2025") in repeating
    assert line_key("1") in numbers


def test_documents_under_five_pages_keep_repeating_lines_but_lose_page_numbers():
    repeating, numbers = furniture_keys(header_pages(4))
    assert repeating == frozenset()
    assert line_key("2") in numbers


def test_a_line_on_too_few_pages_is_not_furniture():
    pages = header_pages(10)
    pages[0] = bands_of((780, 50, "Only on page one"))
    pages[1] = bands_of((780, 50, "Only on page one"))
    repeating, _ = furniture_keys(pages)
    assert line_key("Only on page one") not in repeating  # 2 of 10 pages is 20%


def test_forty_percent_is_enough_and_just_under_is_not():
    def pages_with(count_with):
        return [
            bands_of((780, 50, "Recurring"))
            if i < count_with
            else bands_of((780, 50, f"Other {i}x"))
            for i in range(10)
        ]

    assert line_key("Recurring") in furniture_keys(pages_with(4))[0]
    assert line_key("Recurring") not in furniture_keys(pages_with(3))[0]


# ---- removal -------------------------------------------------------------------------------------------


def clean(pages_text, bands):
    repeating, numbers = furniture_keys(bands)
    return remove_furniture([t.split("\n") for t in pages_text], bands, repeating, numbers)


def test_repeating_header_and_page_numbers_are_removed_but_the_first_header_is_kept():
    bands = header_pages(6, number_format="Page {} of 6")
    pages = [f"ACME REPORT 2025\nPage {n} of 6\nbody {n}" for n in range(1, 7)]
    result = clean(pages, bands)
    assert result[0] == ["ACME REPORT 2025", "body 1"]
    assert all(page == [f"body {n}"] for n, page in enumerate(result[1:], start=2))


def test_a_body_line_equal_to_the_header_survives_once_the_header_copy_is_removed():
    bands = header_pages(6)
    pages = [f"ACME REPORT 2025\nbody {n}" for n in range(1, 7)]
    pages[3] = (
        "ACME REPORT 2025\nACME REPORT 2025\nbody 4"  # header plus the same words in the body
    )
    result = clean(pages, bands)
    assert result[3] == ["ACME REPORT 2025", "body 4"]


def test_a_header_that_the_text_extractor_split_over_two_lines_is_still_removed():
    bands = header_pages(6, header="ACME REPORT 2025")
    pages = ["ACME\nREPORT 2025\nbody"] * 6
    result = clean(pages, bands)
    assert result[0] == ["ACME", "REPORT 2025", "body"]
    assert result[1] == ["body"]


def test_page_numbers_are_removed_on_a_two_page_document_too():
    bands = header_pages(2, number_format="{}")
    result = clean(["ACME REPORT 2025\n1\nbody", "ACME REPORT 2025\n2\nbody"], bands)
    assert result == [["ACME REPORT 2025", "body"], ["ACME REPORT 2025", "body"]]


def test_a_digit_line_in_the_body_is_not_removed_when_the_page_had_no_such_band_line():
    bands = [bands_of((780, 50, "Title"))] * 6
    result = clean(["Title\n5\n7"] * 6, bands)
    assert result[2] == [
        "5",
        "7",
    ]  # "Title" is furniture there; the digits are body (nothing in the footer)


def test_removal_counts_each_band_line_once():
    bands = [bands_of((780, 50, "Same"), (30, 50, "Same"))] + header_pages(5, header="Same")
    pages = ["Same\nSame\nx"] + ["Same\nx"] * 5
    result = clean(pages, bands)
    assert result[0] == ["Same", "x"]  # two band copies on page one: the first is kept, one removed
