const test = require("node:test");
const assert = require("node:assert/strict");
const SegmentOps = require("../../webview/js/segments.js");

test("mergeSegments joins adjacent CJK text without a separator", () => {
  const result = SegmentOps.mergeSegments(
    { start: 0, end: 1, text: "你好", speaker: null, words: [] },
    { start: 1, end: 2, text: "世界", speaker: null, words: [] },
  );

  assert.deepEqual(result, {
    start: 0,
    end: 2,
    speaker: null,
    text: "你好世界",
    words: [],
  });
});

test("mergeSegments separates adjacent Latin text with one space", () => {
  const result = SegmentOps.mergeSegments(
    { start: 0, end: 1, text: "hello", speaker: null, words: [] },
    { start: 1, end: 2, text: "world", speaker: null, words: [] },
  );

  assert.equal(result.text, "hello world");
});

test("splitSegment keeps one segment and aligned word timings without a newline", () => {
  const seg = {
    start: 0,
    end: 4,
    text: "a b c d",
    speaker: 2,
    words: [
      { start: 0, end: 1, text: "a" },
      { start: 1, end: 2, text: "b" },
      { start: 2, end: 3, text: "c" },
      { start: 3, end: 4, text: "d" },
    ],
  };

  assert.deepEqual(SegmentOps.splitSegment(seg, "a b c d"), [seg]);
});

test("splitSegment distributes an unaligned timeline by karaoke-unit counts", () => {
  const result = SegmentOps.splitSegment(
    { start: 0, end: 10, text: "你好世界再見", speaker: 3, words: [] },
    "你好世界\n再見",
  );

  assert.equal(result.length, 2);
  assert.deepEqual(result.map(piece => piece.text), ["你好世界", "再見"]);
  assert.equal(result[0].start, 0);
  assert.ok(Math.abs(result[0].end - 10 * 4 / 6) < 1e-6);
  assert.ok(Math.abs(result[1].start - 10 * 4 / 6) < 1e-6);
  assert.equal(result[1].end, 10);
  assert.deepEqual(result.map(piece => piece.speaker), [3, 3]);
  assert.deepEqual(result.flatMap(piece => piece.words.map(word => word.text)), ["你", "好", "世", "界", "再", "見"]);
});

test("splitSegment assigns aligned words to their manually split lines", () => {
  const seg = {
    start: 0,
    end: 4,
    text: "a b c d",
    speaker: null,
    words: [
      { start: 0, end: 1, text: "a" },
      { start: 1, end: 2, text: "b" },
      { start: 2, end: 3, text: "c" },
      { start: 3, end: 4, text: "d" },
    ],
  };

  assert.deepEqual(SegmentOps.splitSegment(seg, "a b\nc d"), [
    { start: 0, end: 2, text: "a b", speaker: null, words: seg.words.slice(0, 2) },
    { start: 2, end: 4, text: "c d", speaker: null, words: seg.words.slice(2) },
  ]);
});

test("splitSegment treats an edit containing no non-empty lines as cancelled", () => {
  const seg = { start: 1, end: 3, text: "原始內容", speaker: 4, words: [] };

  assert.deepEqual(SegmentOps.splitSegment(seg, "\n\n"), [seg]);
});

test("splitSegment keeps punctuation-only lines with equal fallback windows", () => {
  const result = SegmentOps.splitSegment(
    { start: 0, end: 2, text: "原始", speaker: null, words: [] },
    "!\n?",
  );

  assert.deepEqual(result.map(piece => [piece.start, piece.end, piece.text, piece.words]), [
    [0, 1, "!", []],
    [1, 2, "?", []],
  ]);
});

test("splitSegment safely falls back when an aligned split contains a punctuation-only line", () => {
  const result = SegmentOps.splitSegment(
    {
      start: 0,
      end: 2,
      text: "a",
      speaker: null,
      words: [{ start: 0, end: 2, text: "a" }],
    },
    "a\n...",
  );

  assert.deepEqual(result.map(piece => [piece.start, piece.end, piece.text]), [
    [0, 1, "a"],
    [1, 2, "..."],
  ]);
  assert.deepEqual(result[0].words, [{ start: 0, end: 1, text: "a" }]);
  assert.deepEqual(result[1].words, []);
});

test("mergeSegments concatenates both aligned word arrays", () => {
  const leftWord = { start: 0, end: 1, text: "a" };
  const rightWord = { start: 1, end: 2, text: "b" };

  const result = SegmentOps.mergeSegments(
    { start: 0, end: 1, text: "a", speaker: 1, words: [leftWord] },
    { start: 1, end: 2, text: "b", speaker: 1, words: [rightWord] },
  );

  assert.deepEqual(result.words, [leftWord, rightWord]);
});

test("splitSegment nudges a non-monotonic aligned piece to a neighboring midpoint", () => {
  const result = SegmentOps.splitSegment(
    {
      start: 0,
      end: 5,
      text: "a b c",
      speaker: null,
      words: [
        { start: 0, end: 1, text: "a" },
        { start: 2, end: 1, text: "b" },
        { start: 4, end: 5, text: "c" },
      ],
    },
    "a\nb\nc",
  );

  assert.deepEqual(result.map(piece => [piece.start, piece.end]), [
    [0, 1],
    [2, 2.5],
    [4, 5],
  ]);
});

test("splitSegment removes overlap between aligned pieces at the neighboring midpoint", () => {
  const result = SegmentOps.splitSegment(
    {
      start: 0,
      end: 4,
      text: "a b",
      speaker: null,
      words: [
        { start: 0, end: 3, text: "a" },
        { start: 1, end: 4, text: "b" },
      ],
    },
    "a\nb",
  );

  assert.deepEqual(result.map(piece => [piece.start, piece.end]), [
    [0, 2],
    [2, 4],
  ]);
});

test("splitSegment clamps malformed aligned timings to a monotonic parent timeline", () => {
  const result = SegmentOps.splitSegment(
    {
      start: 0,
      end: 5,
      text: "a b c",
      speaker: null,
      words: [
        { start: -2, end: 9, text: "a" },
        { start: 9, end: 4, text: "b" },
        { start: 4, end: 8, text: "c" },
      ],
    },
    "a\nb\nc",
  );

  for (const piece of result) {
    assert.ok(piece.start >= 0);
    assert.ok(piece.end <= 5);
    assert.ok(piece.end >= piece.start);
  }
  for (let i = 1; i < result.length; i++) {
    assert.ok(result[i].start >= result[i - 1].end);
  }
});
