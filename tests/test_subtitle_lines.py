import subtitle_lines
import pytest


def test_whitespace_only_input_returns_no_lines():
    split_to_lines = getattr(subtitle_lines, "split_to_lines", None)
    assert split_to_lines is not None
    assert split_to_lines("  ") == []


def test_strips_text_before_asr_marker():
    assert subtitle_lines.split_to_lines("language en<asr_text>Hello world.") == [
        "Hello world",
    ]


def test_punctuation_ends_lines_without_being_emitted():
    assert subtitle_lines.split_to_lines("你好，世界。") == ["你好", "世界"]


def test_cjk_text_wraps_at_twenty_characters():
    assert subtitle_lines.split_to_lines(
        "一二三四五六七八九十一二三四五六七八九十甲乙丙丁戊己庚辛壬癸"
    ) == [
        "一二三四五六七八九十一二三四五六七八九十",
        "甲乙丙丁戊己庚辛壬癸",
    ]


def test_latin_lines_wrap_on_whole_words_without_partial_tokens():
    text = (
        "we are going to learn about how to price options using binomial option "
        "method. So first, I want to talk a little bit about the history of "
        "option pricing"
    )
    lines = subtitle_lines.split_to_lines(text)

    assert lines[0] == "we are going to learn about how to price"
    source_words = set(text.replace(",", "").replace(".", "").split())
    assert all(word in source_words for line in lines for word in line.split())
    assert sum("learn" in line.split() for line in lines) == 1
    assert sum("binomial" in line.split() for line in lines) == 1
    assert sum("history" in line.split() for line in lines) == 1


def test_latin_words_keep_internal_apostrophes_and_attached_digits():
    assert subtitle_lines.split_to_lines("don't 3rd") == ["don't 3rd"]


def test_mixed_lines_use_word_limit_and_keep_cjk_attached():
    cjk = "甲" * 20
    assert subtitle_lines.split_to_lines(f"{cjk} hello world") == [
        f"{cjk} hello world",
    ]


def test_oversized_latin_word_stays_whole_on_its_own_line():
    long_word = "supercalifragilisticexpialidocious"
    assert subtitle_lines.split_to_lines(f"hello {long_word} world") == [
        "hello",
        long_word,
        "world",
    ]


def test_assign_ts_uses_proportional_timing_with_line_gap():
    assign_ts = getattr(subtitle_lines, "assign_ts", None)
    assert assign_ts is not None
    result = assign_ts(["ab", "cd"], 0.0, 10.0)

    assert result[0][0:2] == pytest.approx((0.0, 5.0))
    assert result[0][2] == "ab"
    assert result[1][0:2] == pytest.approx((5.08, 10.0))
    assert result[1][2] == "cd"


def test_digits_without_latin_letters_use_character_limit():
    digits = "123456789012345678901"
    assert subtitle_lines.split_to_lines(digits) == [digits[:20], digits[20:]]
