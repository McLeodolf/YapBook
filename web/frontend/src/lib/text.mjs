import { citationSpans } from './reader-text.mjs';
export const PREFETCH_AHEAD = 5;
export const DEFAULT_VOICE = 'en-US-BrianMultilingualNeural';
const titles = new Set('dr. prof. mr. mrs. ms. st. rev. capt. cmdr. lt. gen. col. sgt. adm. sen. rep.'.split(' '));
const abbreviations = new Set('bzw. z.b. u.a. d.h. e.g. i.e. ca. vgl.'.split(' '));
const sentenceStarters = new Set('Then However Meanwhile Finally Afterwards Next He She It They We You I The This That These Those His Her Their Another But Dann Danach Dennoch Allerdings Er Sie Es Wir Ihr Ich Das Dies Diese Dieser Dort Hier Außerdem'.toLowerCase().split(' '));
const ordinalWord = /^(?:jahr(?:hundert|tausend|zehnt)?|geburtstag|tag|woche|monat|platz|rang|klasse|etage|stock|kapitel|abschnitt|band|teil|auflage|ausgabe|version|januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\p{L}*$/iu;

function periodContinues(text, end) {
  // Only nearby words matter; avoid rescanning a whole chapter at every dot.
  const before=text.slice(Math.max(0,end-128),end), after=text.slice(end,end+128);
  if (!before.endsWith('.') || before.endsWith('..')) return false;
  if (/\bet\s+al\.$/i.test(before)) return /^[^\S\r\n]*[,;(]?[^\S\r\n]*(?:18|19|20)\d{2}\b/u.test(after) || /^[^\S\r\n]+\p{Ll}/u.test(after);
  const following=after.match(/^[^\S\r\n]+([\p{L}\p{N}]+)/u), token=before.match(/([\p{L}\p{N}]+(?:\.[\p{L}\p{N}]+)*\.)$/u);
  if (!following || !token) return false;
  const word=token[1], next=following[1], lower=word.toLowerCase(), nextLower=next.toLowerCase();
  if (titles.has(lower)) return /^\p{L}/u.test(next) && !sentenceStarters.has(nextLower);
  if (abbreviations.has(lower) || /(?:z\.\s*b\.|u\.\s*a\.|d\.\s*h\.|e\.\s*g\.|i\.\s*e\.)$/i.test(before)) return !sentenceStarters.has(nextLower);
  const nextInitial=/^[^\S\r\n]+\p{Lu}\./u.test(after);
  if (nextInitial && ['z.','u.','d.','e.','i.'].includes(lower)) return true;
  if (['etc.','usw.','u.s.','u.k.','ph.d.','m.d.','jr.','sr.'].includes(lower) && /^\p{Ll}/u.test(next)) return true;
  if (/^(?:\p{Lu}\.)+$/u.test(word)) return /^\p{Lu}/u.test(next) && (!sentenceStarters.has(nextLower) || nextInitial) || ['de','del','van','von'].includes(nextLower);
  if (['nr.','no.','fig.','vol.','pp.','p.','art.'].includes(lower)) return /^\d/.test(next);
  if (/^\d+\.$/.test(word)) {
    const dateYear=/\b\d{1,2}\.[^\S\r\n]*\d{1,2}\.$/.test(before) && /^\d{4}$/.test(next);
    return /^\p{Ll}/u.test(next) || ordinalWord.test(next) || /^[^\S\r\n]+\d+\./.test(after) || dateYear;
  }
  return false;
}

export function sentenceSpans(text, locale = 'en') {
  const result = [];
  const protectedRanges = citationSpans(text);
  const segmenter = new Intl.Segmenter(locale, { granularity: 'sentence' });
  for (const line of text.matchAll(/[^\n]+/g)) {
    let pending = null;
    for (const segment of segmenter.segment(line[0])) {
      const leading = segment.segment.length - segment.segment.trimStart().length;
      const value = segment.segment.trim();
      if (!value) continue;
      const start=line.index+segment.index+leading, end=start+value.length;
      pending ??= start;
      if (periodContinues(text,end) || protectedRanges.some(([a,b])=>a<end && end<b)) continue;
      result.push([pending,end]); pending=null;
    }
    if (pending !== null) result.push([pending,line.index+line[0].trimEnd().length]);
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
  // The service can report fragments at ordinal/initial periods; highlight one sentence.
  const spans=sentenceSpans(text), merged=[];
  let previous=-1;
  for (const cue of cues) {
    const group=spans.findIndex(([start,end])=>start<=cue.start && cue.start<end);
    if (merged.length && group>=0 && group===previous) {
      const first=merged.at(-1); first.end=cue.end; first.until=Math.max(first.until,cue.until);
    } else merged.push({...cue});
    previous=group;
  }
  return merged;
}

export class SentenceQueue {
  constructor(load, count = PREFETCH_AHEAD + 1) {
    this.load = load; this.count = count;
    this.entries = new Map(); this.ready = new Map(); this.controllers = new Map();
    this.controller = new AbortController();
  }
  retain(parts, index) {
    const wanted = new Set(parts.slice(Math.max(0,index-PREFETCH_AHEAD),index+this.count).map(part=>part.key));
    for (const key of this.entries.keys()) if (!wanted.has(key)) {
      this.controllers.get(key)?.abort(); this.controllers.delete(key);
      this.entries.delete(key); this.ready.delete(key);
    }
  }
  prepare(parts, index) {
    this.retain(parts,index);
    for (const part of parts.slice(index,index+this.count)) if (!this.entries.has(part.key)) {
      const controller = new AbortController();
      this.controllers.set(part.key,controller);
      const promise = Promise.resolve().then(() => {
        this.controller.signal.throwIfAborted(); controller.signal.throwIfAborted();
        return this.load(part,controller.signal);
      }).then(result => {
        if (!controller.signal.aborted && this.entries.get(part.key)===promise) this.ready.set(part.key,result);
        return result;
      });
      promise.catch(() => {});
      this.entries.set(part.key,promise);
    }
    this.tail = Promise.allSettled(this.entries.values());
    return this.entries.get(parts[index]?.key);
  }
  cancel() {
    this.controller.abort();
    for (const controller of this.controllers.values()) controller.abort();
    this.controllers.clear(); this.entries.clear(); this.ready.clear();
  }
}
