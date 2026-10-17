export const DEFAULT_VOICE = 'en-US-BrianMultilingualNeural';
export function sentenceSpans(text, locale = 'en') {
  const result = [];
  const segmenter = new Intl.Segmenter(locale, { granularity: 'sentence' });
  for (const line of text.matchAll(/[^\n]+/g)) {
    for (const segment of segmenter.segment(line[0])) {
      const leading = segment.segment.length - segment.segment.trimStart().length;
      const value = segment.segment.trim();
      if (value) result.push([line.index + segment.index + leading, line.index + segment.index + leading + value.length]);
    }
  }
  return result;
}
export function sentenceParts(text, start = 0, locale = 'en') {
  const parts = [];
  for (const [a, b] of sentenceSpans(text.slice(start), locale)) {
    let cursor = start + a, end = start + b;
    while (cursor < end) {
      let next = Math.min(end, cursor + 700);
      if (next < end) {
        const space = text.lastIndexOf(' ', next);
        if (space > cursor) next = space;
        else if (/[\uD800-\uDBFF]/.test(text[next - 1])) next--;
      }
      parts.push({ start: cursor, end: next, text: text.slice(cursor, next) });
      cursor = next;
      while (cursor < end && /\s/.test(text[cursor])) cursor++;
    }
  }
  return parts;
}
function normalized(text) {
  let value = '', offsets = [], index = 0;
  for (const char of text) {
    const normalized = char.normalize('NFKC').replace(/[“”„]/g, '"').replace(/[‘’]/g, "'").replace(/\u00ad/g, '').toLocaleLowerCase();
    for (const letter of normalized) if (!/[\s\p{Cc}\p{Cf}]/u.test(letter)) {
      value += letter;
      for (let i = 0; i < letter.length; i++) offsets.push([index, index + char.length]);
    }
    index += char.length;
  }
  return { value, offsets };
}
export function alignBoundaries(text, events) {
  const source = normalized(text), cues = []; let cursor = 0;
  for (const event of events) {
    const sentence = normalized(event.text).value;
    if (!sentence) continue;
    const start = source.value.indexOf(sentence, cursor);
    if (start < 0) throw new Error('The sentence timing did not match the text. Please retry this sentence.');
    const end = start + sentence.length;
    cues.push({ start: source.offsets[start][0], end: source.offsets[end - 1][1], time: event.offset / 10000000, until: (event.offset + event.duration) / 10000000 });
    cursor = end;
  }
  if (!cues.length) throw new Error('This voice returned no sentence timing. Please retry or choose another voice.');
  return cues;
}

export class SentenceQueue {
  constructor(load, count = 3) { this.load = load; this.count = count; this.entries = new Map(); this.controller = new AbortController(); }
  prepare(parts, index) {
    const wanted = new Set(parts.slice(index, index + this.count).map(part => part.key));
    for (const key of this.entries.keys()) if (!wanted.has(key)) this.entries.delete(key);
    let chain = this.tail || Promise.resolve();
    for (const part of parts.slice(index, index + this.count)) if (!this.entries.has(part.key)) {
      const promise = chain.catch(() => {}).then(() => {
        this.controller.signal.throwIfAborted();
        return this.load(part, this.controller.signal);
      });
      promise.catch(() => {});
      this.entries.set(part.key, promise); chain = promise;
    }
    this.tail = chain;
    return this.entries.get(parts[index]?.key);
  }
  cancel() { this.controller.abort(); this.entries.clear(); }
}
