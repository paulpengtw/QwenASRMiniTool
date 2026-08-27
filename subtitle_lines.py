"""subtitle_lines.py — 字級時間軸 → 字幕行（後端無關，全引擎共用）

把「字級 (word, start_sec, end_sec) + ASR 原文」轉成字幕行的邏輯集中於此，
讓 OpenVINO / chatllm / CrispASR(Whisper) 三種引擎產出**一致**的字幕斷句與
時間軸（標點切行 + MAX_CHARS/MAX_WORDS 保護 + 孤兒行合併）。

公開符號：
    MAX_CHARS, MAX_WORDS, _ZH_CLAUSE_END, _EN_SENT_END   斷句常數
    text_units(raw_text)                         FA/karaoke 對齊單位
    reconcile_alignment(...)                    補齊不完整 FA 時間軸
    split_to_lines(text)                       原文 → 字幕行
    assign_ts(lines, g0, g1)                   字幕行 → 比例時間軸
    _srt_ts(s)                                秒 → SRT 時間戳
    _merge_orphan_lines(lines)                合併過短孤兒行
    _ts_chatllm_to_subtitle_lines(...)        字級 list → [(start,end,text,spk)]
"""
from __future__ import annotations

import difflib

# ── 斷句常數（與舊 app.py 行為一致）──────────────────────────────────
MAX_CHARS      = 20
MAX_WORDS      = 8
MIN_SUB_SEC    = 0.6
GAP_SEC        = 0.08
_ZH_CLAUSE_END = frozenset('，。？！；：…—、·')
_EN_SENT_END   = frozenset('.,!?;')
_SPLIT_PUNCT   = frozenset('，。？！；：…—、.,!?;:')
_ALIGNMENT_PUNCT = _ZH_CLAUSE_END | _EN_SENT_END | frozenset({':'})


def text_units(raw_text: str) -> list[str]:
    """Return the text units used by forced-alignment reconciliation."""
    units: list[str] = []
    i = 0

    def _is_ascii_alnum(char: str) -> bool:
        return char.isascii() and (char.isalpha() or char.isdigit())

    while i < len(raw_text):
        char = raw_text[i]
        if _is_ascii_alnum(char):
            j = i + 1
            while j < len(raw_text):
                if _is_ascii_alnum(raw_text[j]):
                    j += 1
                elif (raw_text[j] == "'" and j > i and j + 1 < len(raw_text)
                      and _is_ascii_alnum(raw_text[j - 1])
                      and _is_ascii_alnum(raw_text[j + 1])):
                    j += 1
                else:
                    break
            units.append(raw_text[i:j])
            i = j
            continue
        if not char.isspace() and char not in _ALIGNMENT_PUNCT:
            units.append(char)
        i += 1
    return units


def reconcile_alignment(
    ts_items,
    raw_text: str,
    g0: float = 0.0,
    g1: float | None = None,
) -> list[tuple[str, float, float]]:
    """Reconcile an incomplete forced-alignment result with ``raw_text``."""
    units = text_units(raw_text)
    if not ts_items or not units:
        return []

    expanded_items: list[tuple[str, float, float]] = []
    for item in ts_items:
        item_units = text_units(str(item[0]))
        if not item_units:
            continue
        start = float(item[1])
        end = float(item[2])
        duration = (end - start) / len(item_units)
        expanded_items.extend(
            (unit, start + duration * offset,
             start + duration * (offset + 1))
            for offset, unit in enumerate(item_units)
        )
    if not expanded_items:
        return []

    def _normalise(value: str) -> str:
        return str(value).strip("".join(_ALIGNMENT_PUNCT)).casefold()

    unit_keys = [unit.casefold() for unit in units]
    words = [_normalise(item[0]) for item in expanded_items]
    matcher = difflib.SequenceMatcher(None, unit_keys, words, autojunk=False)
    matched = {
        unit_index + offset: expanded_items[word_index + offset]
        for unit_index, word_index, size in matcher.get_matching_blocks()
        for offset in range(size)
    }
    if not matched:
        return []

    result: list[tuple[str, float, float]] = []

    def _append(unit: str, start: float, end: float) -> None:
        start = float(start)
        end = float(end)
        if result:
            start = max(start, result[-1][2])
        end = max(start, end)
        result.append((unit, start, end))

    for unit_index, unit in enumerate(units):
        item = matched.get(unit_index)
        if item is not None:
            _append(unit, item[1], item[2])
            continue
        left = max((index for index in matched if index < unit_index), default=None)
        right = min((index for index in matched if index > unit_index), default=None)
        if left is None and right is not None:
            right_start = float(matched[right][1])
            gap = (right_start - float(g0)) / right
            _append(unit, float(g0) + gap * unit_index,
                    float(g0) + gap * (unit_index + 1))
            continue
        if left is None or right is None:
            if left is None:
                continue
            left_end = float(matched[left][2])
            count = len(units) - left - 1
            right_end = (float(g1) if g1 is not None
                         else left_end + 0.3 * count)
            gap = (right_end - left_end) / count
            offset = unit_index - left
            _append(unit, left_end + gap * (offset - 1),
                    left_end + gap * offset)
            continue
        left_end = float(matched[left][2])
        right_start = float(matched[right][1])
        gap = (right_start - left_end) / (right - left - 1)
        offset = unit_index - left
        _append(unit, left_end + gap * (offset - 1),
                left_end + gap * offset)
    return result


def split_to_lines(text: str) -> list[str]:
    """Split ASR text at punctuation and safe script-aware boundaries.

    Pure non-Latin segments use ``MAX_CHARS``.  Once a segment contains an
    ASCII-letter word, it uses the word boundary instead; mixed CJK/Latin
    text therefore keeps adjacent CJK characters together and joins Latin
    words with single spaces.  The boundary is checked after a word is
    accumulated, matching the forced-alignment path's existing
    ``len(words) > MAX_WORDS`` rule; this preserves the required worked
    example's first line despite its nine whitespace-delimited words.
    """
    if not text or not text.strip():
        return []

    if "<asr_text>" in text:
        text = text.split("<asr_text>", 1)[1]
    text = text.strip()
    lines: list[str] = []
    buf = ""
    word_count = 0
    has_latin = False
    has_long_word = False

    def emit() -> None:
        nonlocal buf, word_count, has_latin, has_long_word
        value = buf.strip()
        if value:
            if has_latin:
                lines.append(value)
            else:
                lines.extend(
                    value[start:start + MAX_CHARS].strip()
                    for start in range(0, len(value), MAX_CHARS)
                    if value[start:start + MAX_CHARS].strip()
                )
        buf = ""
        word_count = 0
        has_latin = False
        has_long_word = False

    def is_ascii_alnum(char: str) -> bool:
        return char.isascii() and (char.isalpha() or char.isdigit())

    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _SPLIT_PUNCT:
            emit()
            i += 1
            continue
        if ch.isascii() and (ch.isalpha() or ch.isdigit()):
            j = i
            while j < len(text):
                if is_ascii_alnum(text[j]):
                    j += 1
                elif (text[j] == "'" and j > i and j + 1 < len(text)
                      and is_ascii_alnum(text[j - 1])
                      and is_ascii_alnum(text[j + 1])):
                    j += 1
                else:
                    break
            word = text[i:j]
            if not any(char.isascii() and char.isalpha() for char in word):
                j = i
            else:
                if has_long_word:
                    emit()
                if len(word) > MAX_CHARS:
                    if buf.strip():
                        emit()
                    buf = word
                    word_count = 1
                    has_latin = True
                    has_long_word = True
                    i = j
                    continue
                if has_latin and word_count > MAX_WORDS:
                    emit()
                if buf and not buf.endswith(" "):
                    buf += " "
                buf += word
                word_count += 1
                has_latin = True
                i = j
                continue
        if ch == " ":
            i += 1
            continue

        if has_long_word:
            emit()
        buf += ch
        i += 1

    emit()
    return lines


def assign_ts(lines: list[str], g0: float, g1: float) -> list[tuple[float, float, str]]:
    if not lines:
        return []
    total = sum(len(line) for line in lines)
    if total == 0:
        return []
    dur = g1 - g0
    result = []
    cur = g0
    cumulative_len = 0
    for i, line in enumerate(lines):
        cumulative_len += len(line)
        proportional_end = g0 + dur * cumulative_len / total
        end = max(cur + MIN_SUB_SEC, proportional_end)
        if i == len(lines) - 1:
            end = max(end, g1)
        result.append((cur, end, line))
        cur = end + GAP_SEC
    return result


def _srt_ts(s: float) -> str:
    ms = int(round(s * 1000))
    hh = ms // 3_600_000; ms %= 3_600_000
    mm = ms // 60_000;    ms %= 60_000
    ss = ms // 1_000;     ms %= 1_000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


# ── 全域輸出格式（"srt" | "txt"）────────────────────────────────────────
# 由 app 啟動 / 設定變更時同步（app._on_output_format_change → 改寫此值）。
# write_transcript() 在 out_format=None 時讀此值，使「批次 / 單檔 / 錄製」
# 三條路徑全域一致；端點需內部解析 SRT，固定以 out_format="srt" 覆寫。
OUTPUT_FORMAT = "srt"


def lines_to_txt(lines: list[tuple[float, float, str, str | None]]) -> str:
    """字幕行 → 純文字（沿用端點既有慣例，與 api_server._parse_srt 後處理一致）。

    • 無說話者：整段文字相連成一行（中文不插空白，重建連續逐字稿）。
    • 有說話者：每段一行，保留「說話者N：」前綴，便於分辨發言者。
    """
    has_spk = any(spk for (_s, _e, _t, spk) in lines)
    if has_spk:
        return "\n".join(
            (f"{spk}：{t}" if spk else t) for (_s, _e, t, spk) in lines
        )
    return "".join(t for (_s, _e, t, _spk) in lines)


def write_transcript(
    ref,
    lines: list[tuple[float, float, str, str | None]],
    out_format: str | None = None,
):
    """把字幕行依格式寫成 .srt 或 .txt，回傳實際輸出路徑（Path）。

    所有引擎（OpenVINO / chatllm / CrispASR）與錄製轉換共用此單一寫出點，
    確保全域輸出格式一致。

    參數：
        ref        : 決定輸出目錄與主檔名的參考路徑（通常為原始音檔）。
        lines      : [(start_sec, end_sec, text, speaker|None), ...]
        out_format : "srt" | "txt"；None 時採用全域 OUTPUT_FORMAT。
                     端點固定傳 "srt"（內部需解析時間軸），不受全域影響。
    """
    from pathlib import Path
    fmt = (out_format or OUTPUT_FORMAT or "srt").lower()
    ref = Path(ref)
    if fmt == "txt":
        out = ref.parent / (ref.stem + ".txt")
        out.write_text(lines_to_txt(lines), encoding="utf-8")
        return out
    out = ref.parent / (ref.stem + ".srt")
    with open(out, "w", encoding="utf-8") as f:
        for idx, (s, e, line, spk) in enumerate(lines, 1):
            prefix = f"{spk}：" if spk else ""
            f.write(f"{idx}\n{_srt_ts(s)} --> {_srt_ts(e)}\n{prefix}{line}\n\n")
    return out


def _merge_orphan_lines(
    lines: list[tuple[float, float, str, str | None]],
    min_chars: int = 1,
    max_gap: float = 0.8,
) -> list[tuple[float, float, str, str | None]]:
    """合併過短的孤立字幕行（如句尾「吧」單獨成行）到相鄰行。

    FA 斷句時 MAX_WORDS 與標點切行偶爾會疊加，在子句中間切一刀，把
    句尾語助詞（吧/啊/呢/了…）留成獨立一行。此處在輸出前把這類「孤兒行」
    併回相鄰行：優先併入前一行（時間連續、同說話者），首行孤兒則併入下一行。
    含拉丁詞時以空格 join，純中文直接相接。

    預設僅併「單字」孤兒：單字幾乎都是句尾語助詞，向後併入前一行最安全；
    兩字以上可能是句首短詞，向後併易誤接，故不處理。
    """
    if not lines:
        return lines

    def _has_latin(t: str) -> bool:
        return any(c.isascii() and c.isalpha() for c in t)

    def _vlen(t: str) -> int:
        return len(t.replace(" ", ""))

    def _is_orphan(t: str) -> bool:
        # 純中文且可見字數極少才視為孤兒；含拉丁詞（英文/數字詞）不併
        return (not _has_latin(t)) and 0 < _vlen(t) <= min_chars

    def _join(a: str, b: str) -> str:
        sep = " " if (_has_latin(a) or _has_latin(b)) else ""
        return f"{a}{sep}{b}"

    merged: list[tuple[float, float, str, str | None]] = []
    for (s, e, t, spk) in lines:
        if (_is_orphan(t) and merged
                and merged[-1][3] == spk
                and s - merged[-1][1] <= max_gap):
            ps, _pe, pt, pspk = merged[-1]
            merged[-1] = (ps, e, _join(pt, t), pspk)
        else:
            merged.append((s, e, t, spk))

    # 首行仍是孤兒（無前一行可併）→ 併入下一行
    if len(merged) >= 2 and _is_orphan(merged[0][2]):
        s0, _e0, t0, spk0 = merged[0]
        s1, e1, t1, spk1 = merged[1]
        if spk0 == spk1 and s1 - merged[0][1] <= max_gap:
            merged[1] = (s0, e1, _join(t0, t1), spk1)
            merged.pop(0)

    return merged


def _merge_orphan_lines_rich(
    lines: list[tuple],
    min_chars: int = 1,
    max_gap: float = 0.8,
) -> list[tuple]:
    """`_merge_orphan_lines` 的 5-tuple 版（卡拉OK字級用）。

    行為與 4-tuple 版完全相同（同樣的孤兒判定、間隔/說話者條件），差別只在
    併行時連同第 5 元素 ``words`` 字級清單一起串接，使字幕卡與卡拉OK逐字
    高亮的斷句保持一致。
    """
    if not lines:
        return lines

    def _has_latin(t: str) -> bool:
        return any(c.isascii() and c.isalpha() for c in t)

    def _vlen(t: str) -> int:
        return len(t.replace(" ", ""))

    def _is_orphan(t: str) -> bool:
        return (not _has_latin(t)) and 0 < _vlen(t) <= min_chars

    def _join(a: str, b: str) -> str:
        sep = " " if (_has_latin(a) or _has_latin(b)) else ""
        return f"{a}{sep}{b}"

    merged: list[tuple] = []
    for (s, e, t, spk, w) in lines:
        if (_is_orphan(t) and merged
                and merged[-1][3] == spk
                and s - merged[-1][1] <= max_gap):
            ps, _pe, pt, pspk, pw = merged[-1]
            merged[-1] = (ps, e, _join(pt, t), pspk, pw + w)
        else:
            merged.append((s, e, t, spk, w))

    if len(merged) >= 2 and _is_orphan(merged[0][2]):
        s0, _e0, t0, spk0, w0 = merged[0]
        s1, e1, t1, spk1, w1 = merged[1]
        if spk0 == spk1 and s1 - merged[0][1] <= max_gap:
            merged[1] = (s0, e1, _join(t0, t1), spk1, w0 + w1)
            merged.pop(0)

    return merged


def _ts_chatllm_to_subtitle_lines(
    ts_items,
    raw_text: str,
    chunk_offset: float,
    spk: str | None,
    cc,
    simplified: bool,
    break_on_space: bool = False,
    with_words: bool = False,
):
    """字級 (word, start_sec, end_sec) + ASR 原文 → 字幕行。

    標點切行 + MAX_CHARS/MAX_WORDS 保護；word_list 直接取自字級時間軸，
    與時間 1:1 對應，後端無關（chatllm FA / Whisper 字級皆適用）。

    參數：
        ts_items: list[tuple[str, float, float]]  → (word, start_sec, end_sec)
        break_on_space: True 時把 raw_text 的「空白」也當切點。
            用於 Whisper（無標點，但以空白標記語句邊界）→ 等同 Qwen 在標點切，
            逼近 Qwen 斷句品質。Qwen/chatllm 路徑維持 False（空白僅分隔拉丁詞）。
        with_words: True 時每行多帶一個 ``words`` 字級清單（卡拉OK逐字高亮用），
            回傳 5-tuple ``(start, end, text, spk, words)``；
            ``words = [{"start": 秒, "end": 秒, "text": 顯示字}, ...]``。
            預設 False → 維持既有 4-tuple 行為（SRT/批次/端點完全不受影響）。

    回傳：
        with_words=False → list[(start, end, text, spk)]
        with_words=True  → list[(start, end, text, spk, words)]
    """
    _all_punct = _ZH_CLAUSE_END | _EN_SENT_END
    MAX_ZH_CHARS = MAX_CHARS
    # 內部一律以 5-tuple (start, end, text, spk, words) 累積，回傳前依 with_words 決定保留與否
    result: list[tuple] = []

    if not ts_items or not raw_text.strip():
        return result

    word_list = [w for (w, _s, _e) in ts_items]
    n = len(ts_items)

    # 繁化：text（整行）沿用既有「整行轉換」確保 SRT 輸出零變化；
    # words[].text 走「逐字轉換」（卡拉OK高亮單位）——兩者在極少數 s2twp
    # 詞組轉換情境可能有細微差異，但卡拉OK檢視只讀 words，不影響字幕卡/SRT。
    def _conv(s: str) -> str:
        return cc.convert(s) if (not simplified and cc is not None) else s

    seg_idx:   list[int] = []   # 當前行的 ts_items 索引
    seg_words: list[str] = []   # 當前行的原始 word
    ri = 0                      # raw_text 掃描位置

    def _is_latin_word(w: str) -> bool:
        return any(c.isascii() and c.isalpha() for c in w)

    def _emit():
        nonlocal seg_idx, seg_words
        if not seg_idx:
            seg_idx = []; seg_words = []
            return
        start = chunk_offset + ts_items[seg_idx[0]][1]
        end   = chunk_offset + ts_items[seg_idx[-1]][2]
        if any(_is_latin_word(w) for w in seg_words):
            text = " ".join(seg_words)
        else:
            text = "".join(seg_words)
        text = _conv(text)
        # 字級清單：每個 ts_item → 一個高亮單位（中文＝單字、拉丁＝整詞）
        words = [
            {"start": chunk_offset + ts_items[k][1],
             "end":   chunk_offset + ts_items[k][2],
             "text":  _conv(word_list[k])}
            for k in seg_idx
        ]
        if end > start and text.strip():
            result.append((start, end, text.strip(), spk, words))
        seg_idx = []; seg_words = []

    def _over_limit() -> bool:
        if any(_is_latin_word(w) for w in seg_words):
            return len(seg_words) > MAX_WORDS
        return sum(len(w) for w in seg_words) > MAX_ZH_CHARS

    for wi in range(n):
        word = word_list[wi]

        # 在 raw_text 中前進到 word 位置；遇到標點（或 whisper 空白）→ 先切行
        hit_punct = False
        while ri < len(raw_text):
            c = raw_text[ri]
            if c in _all_punct:
                hit_punct = True; ri += 1; continue
            if c == " ":
                if break_on_space:
                    hit_punct = True   # whisper：空白＝語句邊界，視同切點
                ri += 1; continue
            break

        if hit_punct:
            _emit()

        seg_idx.append(wi)
        seg_words.append(word)

        # 跳過 word 在 raw_text 中佔用的字元（依長度計數，忽略標點/空格）
        consumed = 0
        word_len = len(word)
        while ri < len(raw_text) and consumed < word_len:
            c = raw_text[ri]
            if c in _all_punct or c == " ":
                ri += 1; continue
            ri += 1; consumed += 1

        if _over_limit():
            _emit()

    _emit()
    merged = _merge_orphan_lines_rich(result)
    if with_words:
        return merged
    return [(s, e, t, spk) for (s, e, t, spk, _w) in merged]
