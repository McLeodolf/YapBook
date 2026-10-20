// Keep citation recognition equivalent to reader_text.py; display text is untouched.
const name = "[A-ZÀ-ÖØ-Þ][\\p{L}\\p{N}_'’\\-]+";
const authors = `${name}(?:\\s+(?:et\\s+al\\.|(?:and|und|&)\\s+${name}))?`;
const year = '(?:18|19|20)\\d{2}[a-z]?';
const patterns = [
  /\[\s*\d+(?:\s*[,;–—-]\s*\d+)*\s*\]/gu,
  new RegExp(`\\((?:${authors}\\s*,?\\s*${year}(?:\\s*[,;]\\s*(?:${authors}\\s*,?\\s*)?${year})*(?:\\s*,\\s*(?:p{1,2}\\.|S\\.)\\s*\\d+(?:[–-]\\d+)?)?)\\)`, 'gu'),
  new RegExp(`\\b${authors}\\s*\\(\\s*${year}(?:\\s*[,;]\\s*${year})*\\s*\\)`, 'gu'),
  new RegExp(`\\b${name}\\s+et\\s+al\\.\\s*,?\\s*${year}\\b`, 'gu'),
];
export function citationSpans(text, marked = []) {
  const ranges = [...marked];
  for (const pattern of patterns) for (const match of text.matchAll(pattern)) ranges.push([match.index, match.index + match[0].length]);
  const merged = [];
  for (let [start, end] of ranges.sort((a,b)=>a[0]-b[0])) {
    start = Math.max(0,start); end = Math.min(text.length,end);
    if (start >= end) continue;
    if (merged.length && start <= merged.at(-1)[1]) merged.at(-1)[1] = Math.max(end,merged.at(-1)[1]);
    else merged.push([start,end]);
  }
  return merged;
}
export function speechProjection(text, readCitations = true, marked = []) {
  const removed = new Set();
  if (!readCitations) for (const [start,end] of citationSpans(text,marked)) for (let i=start;i<end;i++) removed.add(i);
  const letters=[], offsets=[];
  for (let i=0;i<text.length;i++) {
    const char=text[i];
    if (removed.has(i)) continue;
    if (/\s/u.test(char) && (!letters.length || /\s/u.test(letters.at(-1)))) continue;
    if (/[,.;:!?]/u.test(char) && letters.length && /\s/u.test(letters.at(-1))) { letters.pop(); offsets.pop(); }
    letters.push(char); offsets.push(i);
  }
  while (letters.length && /\s/u.test(letters.at(-1))) { letters.pop(); offsets.pop(); }
  const spoken=letters.join('');
  return /[\p{L}\p{N}]/u.test(spoken) ? {text:spoken,offsets} : {text:'',offsets:[]};
}
export function searchBook(sections, query) {
  const words=query.trim().split(/\s+/u).filter(Boolean);
  if (!words.length) return [];
  const escaped=words.map(word=>word.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'));
  const pattern=new RegExp(escaped.join('\\s+'),'giu'), results=[];
  sections.forEach(({text},section)=>{
    for (const match of text.matchAll(pattern)) results.push({section,start:match.index,end:match.index+match[0].length});
  });
  return results;
}
