(function () {
  "use strict";

  function karaokeUnits(text) {
    const units = [];
    let latin = "";
    const flushLatin = () => {
      if (latin) { units.push(latin); latin = ""; }
    };
    for (const ch of String(text || "")) {
      if (/[A-Za-z0-9]/.test(ch)) {
        latin += ch;
      } else {
        flushLatin();
        if (ch.trim() && !/[\p{P}\p{S}]/u.test(ch)) units.push(ch);
      }
    }
    flushLatin();
    return units;
  }

  function interpWords(seg, units) {
    const dur = units.length ? (seg.end - seg.start) / units.length : 0;
    return units.map((unit, i) => ({
      start: seg.start + i * dur,
      end: seg.start + (i + 1) * dur,
      text: unit,
    }));
  }

  function reflowWords(seg, text) {
    const units = karaokeUnits(text);
    const old = Array.isArray(seg.words) ? seg.words : [];
    if (old.length && old.length === units.length) {
      return old.map((word, i) => ({ start: word.start, end: word.end, text: units[i] }));
    }
    return interpWords(seg, units);
  }

  function splitSegment(seg, text) {
    const pieces = String(text == null ? "" : text)
      .split(/\r?\n/)
      .map(piece => piece.trim())
      .filter(Boolean);
    if (!pieces.length) {
      return [{
        ...seg,
        text: seg.text,
        words: Array.isArray(seg.words) ? seg.words.map(word => ({ ...word })) : [],
      }];
    }
    if (pieces.length === 1) {
      return [{ ...seg, text: pieces[0], words: reflowWords(seg, pieces[0]) }];
    }

    const units = pieces.map(piece => karaokeUnits(piece));
    const totalUnits = units.reduce((sum, pieceUnits) => sum + pieceUnits.length, 0);
    const oldWords = Array.isArray(seg.words) ? seg.words : [];
    const hasZeroUnitPiece = units.some(pieceUnits => !pieceUnits.length);
    if (oldWords.length && oldWords.length === totalUnits && !hasZeroUnitPiece) {
      let offset = 0;
      const aligned = pieces.map((piece, i) => {
        const pieceUnits = units[i];
        const firstWordIndex = offset;
        const lastWordIndex = offset + pieceUnits.length - 1;
        const words = oldWords.slice(offset, offset + pieceUnits.length).map((word, j) => ({
          start: word.start,
          end: word.end,
          text: pieceUnits[j],
        }));
        offset += pieceUnits.length;
        let start = i === 0 ? seg.start : words[0].start;
        let end = i === pieces.length - 1 ? seg.end : words[words.length - 1].end;
        if (end <= start) {
          const previous = oldWords[firstWordIndex - 1];
          const next = oldWords[lastWordIndex + 1];
          const before = previous ? previous.end : seg.start;
          const after = next ? next.start : seg.end;
          const midpoint = (before + after) / 2;
          if (i === pieces.length - 1) start = midpoint;
          else end = midpoint;
        }
        return {
          segment: {
            ...seg,
            start,
            end,
            text: piece,
            words,
          },
          firstWordIndex,
          lastWordIndex,
        };
      });
      for (let i = 1; i < aligned.length; i++) {
        if (aligned[i].segment.start < aligned[i - 1].segment.end) {
          const previousWord = oldWords[aligned[i - 1].lastWordIndex];
          const currentWord = oldWords[aligned[i].firstWordIndex];
          const midpoint = (previousWord.end + currentWord.start) / 2;
          aligned[i - 1].segment.end = midpoint;
          aligned[i].segment.start = midpoint;
        }
      }
      let cursor = seg.start;
      aligned.forEach(item => {
        const piece = item.segment;
        piece.start = Math.max(seg.start, Math.min(seg.end, piece.start));
        piece.end = Math.max(seg.start, Math.min(seg.end, piece.end));
        piece.start = Math.max(piece.start, cursor);
        piece.end = Math.max(piece.end, piece.start);
        cursor = piece.end;
      });
      return aligned.map(item => item.segment);
    }

    const duration = seg.end - seg.start;
    if (!totalUnits) {
      const pieceDuration = pieces.length ? duration / pieces.length : 0;
      return pieces.map((piece, i) => ({
        ...seg,
        start: seg.start + i * pieceDuration,
        end: seg.start + (i + 1) * pieceDuration,
        text: piece,
        words: [],
      }));
    }

    // A punctuation-only piece has no timing weight; give it one fallback slot
    // so it remains visible and the output timeline stays contiguous.
    const weights = units.map(pieceUnits => pieceUnits.length || 1);
    const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
    let usedWeight = 0;
    return pieces.map((piece, i) => {
      const start = i === 0 ? seg.start : seg.start + duration * usedWeight / totalWeight;
      usedWeight += weights[i];
      const end = i === pieces.length - 1 ? seg.end : seg.start + duration * usedWeight / totalWeight;
      const window = { start, end };
      return { ...seg, start, end, text: piece, words: interpWords(window, units[i]) };
    });
  }

  function mergeSegments(a, b) {
    const left = a.text || "";
    const right = b.text || "";
    const separator = /[A-Za-z0-9]$/.test(left) || /^[A-Za-z0-9]/.test(right) ? " " : "";
    const leftWords = Array.isArray(a.words) ? a.words : [];
    const rightWords = Array.isArray(b.words) ? b.words : [];
    return {
      start: a.start,
      end: b.end,
      speaker: a.speaker,
      text: left + separator + right,
      words: leftWords.length && rightWords.length ? [...leftWords, ...rightWords] : [],
    };
  }

  const SegmentOps = { splitSegment, mergeSegments };
  if (typeof module !== "undefined") module.exports = SegmentOps;
  else window.SegmentOps = SegmentOps;
})();
