import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sentenceSpans,sentenceParts,alignBoundaries,SentenceQueue} from '../src/lib/text.mjs';

test('ordinals, initials and abbreviations remain in one request with original offsets',()=>{
  const sentences=[
    'Im 17. Jahrhundert entstand ein kleines Dorf.',
    'Wir feiern ihren 105. Geburtstag.',
    'wir feiern ihren 105. geburtstag.',
    'Am 3. Mai feiern wir den 1000. Geburtstag.',
    'Am 3. 5. 2024 wurde er geboren.',
    'Matthew C. Perry arrived in Japan.',
    'J. R. R. Tolkien wrote a book.',
    'Dr. Smith met Mr. Brown.',
    'Dr. Weber liest z. B. 3.14 Seiten.',
    'Das ist z.B. ein Beispiel bzw. eine Erklärung.',
    'The U.S. economy grew.',
    'Im 17.\u00a0Jahrhundert lebte Matthew C.\u00a0Perry.'
  ];
  for(const locale of ['en','de'])for(const sentence of sentences){
    const text='  '+sentence+' Danach geht es weiter.  ', expected=[sentence,'Danach geht es weiter.'];
    assert.deepEqual(sentenceSpans(text,locale).map(([a,b])=>text.slice(a,b)),expected,`${locale}: ${sentence}`);
    const parts=sentenceParts(text,0,locale);
    assert.deepEqual(parts.map(p=>p.text),expected,`${locale}: ${sentence}`);
    for(const part of parts)assert.equal(text.slice(part.start,part.end),part.text);
  }
});

test('real sentence endings and explicit breaks still split',()=>{
  const cases=[
    ['Er wurde 17.','Danach ging er nach Hause.'],
    ['He was 105.','Then they celebrated.'],
    ['This is plan A.','Then we try again.'],
    ['Bring pens etc.','Then we start.'],
    ['He lives in the U.S.','The next visitor is from Japan.'],
    ['“Matthew C. Perry arrived.”','Another visitor followed.'],
  ];
  for(const locale of ['en','de'])for(const expected of cases){
    assert.deepEqual(sentenceParts(expected.join(' '),0,locale).map(p=>p.text),expected);
  }
  const text='17.\nJahrhundert\nDr.\nSmith\n105.\nGeburtstag';
  assert.deepEqual(sentenceParts(text).map(p=>p.text),text.split('\n'));
});

test('service fragments highlight the whole logical sentence throughout playback',()=>{
  for(const fragments of [
    ['Im 17.','Jahrhundert entstand ein kleines Dorf.'],
    ['Wir feiern ihren 105.','Geburtstag.'],
    ['Matthew C.','Perry arrived in Japan.'],
  ]){
    const sentence=fragments.join(' '),text='  '+sentence+' Another sentence.';
    const events=[...fragments,'Another sentence.'].map((text,i)=>({text,offset:1000000+i*20000000,duration:15000000}));
    const cues=alignBoundaries(text,events);
    assert.deepEqual(cues.map(c=>text.slice(c.start,c.end)),[sentence,'Another sentence.']);
    assert.equal(cues[0].time,0.1);assert.equal(cues[0].until,3.6);assert.equal(cues[1].time,4.1);
  }
});

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
