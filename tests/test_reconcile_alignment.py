import subtitle_lines
import pytest


def test_text_units_groups_latin_words_and_splits_cjk_and_hangul():
    text_units = getattr(subtitle_lines, "text_units", None)
    assert text_units is not None
    assert text_units("Hello, don't 3rd! 你好世界 안녕하세요。") == [
        "Hello", "don't", "3rd", "你", "好", "世", "界",
        "안", "녕", "하", "세", "요",
    ]


def test_reconcile_alignment_keeps_complete_coverage_unchanged():
    reconcile_alignment = getattr(subtitle_lines, "reconcile_alignment", None)
    assert reconcile_alignment is not None
    assert reconcile_alignment(
        [("hello", 0.0, 0.5), ("world", 0.6, 1.0)],
        "hello world",
    ) == [("hello", 0.0, 0.5), ("world", 0.6, 1.0)]


def test_reconcile_alignment_interpolates_a_dropped_middle_word():
    reconcile_alignment = subtitle_lines.reconcile_alignment
    assert reconcile_alignment(
        [("we", 0.0, 0.2), ("going", 0.5, 0.8)],
        "we are going",
    ) == [
        ("we", 0.0, 0.2),
        ("are", 0.2, 0.5),
        ("going", 0.5, 0.8),
    ]


def test_reconcile_alignment_ignores_case_and_clause_punctuation():
    assert subtitle_lines.reconcile_alignment(
        [("Hello,", 0.0, 0.5), ("WORLD", 0.6, 1.0)],
        "hello world.",
    ) == [("hello", 0.0, 0.5), ("world", 0.6, 1.0)]


def test_reconcile_alignment_interpolates_dropped_cjk_characters():
    result = subtitle_lines.reconcile_alignment(
        [("你", 0.0, 0.3), ("界", 0.9, 1.2)],
        "你好世界",
    )
    assert [item[0] for item in result] == ["你", "好", "世", "界"]
    for item, expected in zip(result, ((0.0, 0.3), (0.3, 0.6),
                                      (0.6, 0.9), (0.9, 1.2))):
        assert item[1:] == pytest.approx(expected)


def test_reconcile_alignment_expands_multi_syllable_hangul_items():
    result = subtitle_lines.reconcile_alignment(
        [("안녕", 0.0, 1.0), ("세요", 1.0, 2.0)],
        "안녕하세요",
    )
    assert [item[0] for item in result] == ["안", "녕", "하", "세", "요"]
    for item, expected in zip(result, ((0.0, 0.5), (0.5, 1.0),
                                      (1.0, 1.0), (1.0, 1.5), (1.5, 2.0))):
        assert item[1:] == pytest.approx(expected)


def test_reconcile_alignment_returns_empty_when_nothing_matches():
    assert subtitle_lines.reconcile_alignment(
        [("foo", 0.0, 1.0)],
        "bar baz",
    ) == []


def test_reconcile_alignment_returns_empty_for_empty_aligner_items():
    assert subtitle_lines.reconcile_alignment([], "abc") == []


def test_reconcile_alignment_interpolates_a_leading_dropped_unit():
    result = subtitle_lines.reconcile_alignment(
        [("b", 1.0, 2.0)],
        "a b",
        g0=0.0,
    )
    assert result == [("a", 0.0, 1.0), ("b", 1.0, 2.0)]


def test_reconciled_alignment_preserves_dropped_word_in_line_builder():
    ts_items = subtitle_lines.reconcile_alignment(
        [("we", 0.0, 0.2), ("going", 0.5, 0.8)],
        "we are going.",
    )
    lines = subtitle_lines._ts_chatllm_to_subtitle_lines(
        ts_items, "we are going.", 0.0, None, None, True,
    )
    assert lines == [(0.0, 0.8, "we are going", None)]


def test_reconcile_alignment_appends_trailing_units_when_g1_is_omitted():
    result = subtitle_lines.reconcile_alignment(
        [("a", 0.0, 1.0)],
        "a b",
    )
    assert result == [("a", 0.0, 1.0), ("b", 1.0, 1.3)]


def test_reconcile_alignment_uses_supplied_g1_for_trailing_units():
    result = subtitle_lines.reconcile_alignment(
        [("a", 0.0, 1.0)],
        "a b",
        g1=2.0,
    )
    assert result == [("a", 0.0, 1.0), ("b", 1.0, 2.0)]


def test_reconcile_alignment_keeps_output_timestamps_monotonic():
    result = subtitle_lines.reconcile_alignment(
        [("a", 1.0, 0.5), ("b", 0.25, 0.2)],
        "a b",
    )
    assert all(end >= start for _text, start, end in result)
    assert all(result[i][2] <= result[i + 1][1]
               for i in range(len(result) - 1))
