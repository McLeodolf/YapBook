import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sentenceParts,alignBoundaries,SentenceQueue} from '../src/lib/text.mjs';

test('one sentence per request, with heading and paragraph breaks',()=>{
  const text='Chapter 2\nAccepting Yourself\nOne little sentence. Another follows.\nA final paragraph.';
  const parts=sentenceParts(text);
  assert.deepEqual(parts.map(p=>p.text),['Chapter 2','Accepting Yourself','One little sentence.','Another follows.','A final paragraph.']);
  for(const part of parts)assert.equal(text.slice(part.start,part.end),part.text);
});
test('long sentences stay bounded and preserve astral characters',()=>{
  const parts=sentenceParts('A '+ '📖'.repeat(800)+'.');
  assert.ok(parts.every(p=>p.text.length<=700 && !/^[\uDC00-\uDFFF]|[\uD800-\uDBFF]$/.test(p.text)));
});
test('timing handles Unicode quotes and matches original offsets',()=>{
  const text='“Hello,” she said. Another sentence.';
  const cues=alignBoundaries(text,[{text:'"Hello," she said.',offset:10000000,duration:20000000},{text:'Another sentence.',offset:30000000,duration:20000000}]);
  assert.equal(text.slice(cues[0].start,cues[0].end),'“Hello,” she said.');
  assert.equal(cues[1].time,3);
  assert.throws(()=>alignBoundaries(text,[{text:'wrong text',offset:0,duration:1}]));
});
test('queue prepares current plus exactly two following sentences and reuses them',async()=>{
  const calls=[],parts=Array.from({length:8},(_,i)=>({key:String(i),text:`Sentence ${i}.`}));
  const queue=new SentenceQueue(async p=>{calls.push(p.key);return p.key;});
  assert.equal(await queue.prepare(parts,0),'0');await queue.tail;
  assert.deepEqual(calls,['0','1','2']);
  assert.equal(await queue.prepare(parts,1),'1');await queue.tail;
  assert.deepEqual(calls,['0','1','2','3']);assert.equal(queue.entries.size,3);
  queue.cancel();assert.equal(queue.entries.size,0);
});
test('cancel stops queued requests before they contact the service',async()=>{
  const calls=[],parts=[{key:'0'},{key:'1'},{key:'2'}];
  let release;const queue=new SentenceQueue(async p=>{calls.push(p.key);await new Promise(r=>release=r);});
  queue.prepare(parts,0);await new Promise(r=>setTimeout(r,0));queue.cancel();release();
  await queue.tail.catch(()=>{});assert.deepEqual(calls,['0']);
});
