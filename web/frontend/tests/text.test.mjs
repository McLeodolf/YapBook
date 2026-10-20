import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sentenceSpans,sentenceParts,alignBoundaries,SentenceQueue} from '../src/lib/text.mjs';
import {AudioCache} from '../src/lib/audio-cache.mjs';

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
test('queue prepares current plus exactly five following sentences and reuses them',async()=>{
  const calls=[],parts=Array.from({length:8},(_,i)=>({key:String(i),text:`Sentence ${i}.`}));
  const queue=new SentenceQueue(async p=>{calls.push(p.key);return p.key;});
  assert.equal(await queue.prepare(parts,0),'0');await queue.tail;
  assert.deepEqual(calls,['0','1','2','3','4','5']);
  assert.equal(await queue.prepare(parts,1),'1');await queue.tail;
  assert.deepEqual(calls,['0','1','2','3','4','5','6']);assert.equal(queue.entries.size,7);
  queue.cancel();assert.equal(queue.entries.size,0);
});
test('cancel stops queued requests before they contact the service',async()=>{
  const calls=[],parts=[{key:'0'},{key:'1'},{key:'2'}];
  const queue=new SentenceQueue(async p=>{calls.push(p.key);});
  queue.prepare(parts,0);queue.cancel();
  await queue.tail;assert.deepEqual(calls,[]);
});

test('rolling buffer refills one slot without waiting for slower future sentences',async()=>{
  const calls=[],release=new Map(),parts=Array.from({length:9},(_,i)=>({key:String(i)}));
  const queue=new SentenceQueue(p=>{calls.push(p.key);return new Promise(resolve=>release.set(p.key,resolve));});
  const first=queue.prepare(parts,0);await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(calls,['0','1','2','3','4','5']);
  release.get('5')('five');release.get('0')('zero');
  assert.equal(await first,'zero');
  assert.equal(queue.ready.get('5'),'five');
  assert.equal(queue.ready.has('1'),false);
  const second=queue.prepare(parts,1);
  await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(calls,['0','1','2','3','4','5','6']);
  assert.equal(queue.prepare(parts,1),second);
  release.get('1')('one');assert.equal(await second,'one');
  const third=queue.prepare(parts,2);await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(calls,['0','1','2','3','4','5','6','7']);
  release.get('2')('two');assert.equal(await third,'two');
  for(const key of ['3','4','6','7'])release.get(key)(key);
  await queue.tail;queue.cancel();
});

test('rolling buffer drains at the end without duplicate requests',async()=>{
  const calls=[],parts=Array.from({length:12},(_,i)=>({key:String(i)}));
  const queue=new SentenceQueue(async part=>{calls.push(part.key);return part.key;});
  for(let index=0;index<parts.length;index++) {
    assert.equal(await queue.prepare(parts,index),parts[index].key);
    await queue.tail;
    assert.equal(queue.entries.size,Math.min(5,index)+Math.min(6,parts.length-index));
    assert.equal(queue.ready.size,Math.min(5,index)+Math.min(6,parts.length-index));
    assert.equal(calls.length,Math.min(parts.length,index+6));
  }
  assert.deepEqual(calls,parts.map(part=>part.key));queue.cancel();
});


test('five previous and five following sentences remain ready for reverse navigation',async()=>{
  const calls=[],parts=Array.from({length:20},(_,i)=>({key:String(i)}));
  const cache=new AudioCache(async()=>null,async()=>{});
  const queue=new SentenceQueue(part=>cache.get(part.key,'voice',0,async()=>{calls.push(part.key);return part.key;}));
  for(let index=0;index<=8;index++) {await queue.prepare(parts,index);await queue.tail;}
  assert.deepEqual([...queue.ready.keys()],parts.slice(3,14).map(part=>part.key));
  assert.equal(queue.entries.size,11);
  assert.equal(await queue.prepare(parts,3),'3');await queue.tail;
  assert.deepEqual(calls,parts.slice(0,14).map(part=>part.key));
  for(let index=4;index<=8;index++) {await queue.prepare(parts,index);await queue.tail;}
  assert.ok(queue.entries.size<=11);
  assert.deepEqual(calls,parts.slice(0,14).map(part=>part.key));
  queue.cancel();
});

test('leaving the window cancels only consumers outside the new playback neighborhood',async()=>{
  const calls=[],parts=Array.from({length:20},(_,i)=>({key:String(i)}));
  const queue=new SentenceQueue(async(part,signal)=>{calls.push({key:part.key,signal});return part.key;});
  await queue.prepare(parts,0);await queue.tail;
  await queue.prepare(parts,8);await queue.tail;
  assert.ok(calls.filter(call=>Number(call.key)<3).every(call=>call.signal.aborted));
  assert.ok(calls.filter(call=>Number(call.key)>=3).every(call=>!call.signal.aborted));
  assert.deepEqual([...queue.ready.keys()],['3','4','5','8','9','10','11','12','13']);
  queue.cancel();
});
