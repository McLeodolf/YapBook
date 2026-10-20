import test from 'node:test';
import assert from 'node:assert/strict';
import {speechProjection,searchBook} from '../src/lib/reader-text.mjs';
import {sentenceParts} from '../src/lib/text.mjs';
import {AudioCache} from '../src/lib/audio-cache.mjs';
import {SpeechRPC} from '../src/lib/rpc.mjs';

test('et al. with years stays intact but a genuine following sentence splits',()=>{
  for(const locale of ['en','de']) for(const text of ['Smith et al. (2021) found this.','Evidence (Smith et al., 2021) supports it.','Smith et al. 2021 supports it.','Smith et al. reported this.']) {
    assert.deepEqual(sentenceParts(text+' Then we continued.',0,locale).map(p=>p.text),[text,'Then we continued.']);
  }
  assert.deepEqual(sentenceParts('We consulted Smith et al. Then we left.').map(p=>p.text),['We consulted Smith et al.','Then we left.']);
});
test('citations are omitted only in speech; source offsets and normal numbers remain',()=>{
  const source='Evidence (Smith et al., 2021) supports this [12]. Another point¹ matters. x² = 4 in 2020.';
  const marked=[[source.indexOf('¹'),source.indexOf('¹')+1]];
  const projection=speechProjection(source,false,marked);
  assert.equal(projection.text,'Evidence supports this. Another point matters. x² = 4 in 2020.');
  for(let i=0;i<projection.text.length;i++)assert.equal(source[projection.offsets[i]],projection.text[i]);
  assert.equal(speechProjection(source,true,marked).text,source);
  assert.equal(speechProjection('[12]',false).text,'');
  assert.equal(speechProjection('Smith et al. (2021) found a pattern.',false).text,'found a pattern.');
  assert.equal(speechProjection('“A quote.” It was cold (in 2021).',false).text,'“A quote.” It was cold (in 2021).');
});
test('search covers sections, escapes regex and preserves exact original offsets',()=>{
  const sections=[{text:'Ein Satz. X [12] plus.'},{text:'Another SATZ. X\n[12] plus.'}];
  const hits=searchBook(sections,'x [12]');assert.equal(hits.length,2);
  assert.deepEqual(hits.map(h=>sections[h.section].text.slice(h.start,h.end)),['X [12]','X\n[12]']);
  assert.equal(searchBook(sections,'   ').length,0);
});
test('identical in-flight and completed speech uses one request, including new cache instances',async()=>{
  const disk=new Map(),read=async k=>disk.get(k),write=async(k,v)=>disk.set(k,v);
  const cache=new AudioCache(read,write);let calls=0,release;
  const load=()=>{calls++;return new Promise(r=>release=r);};
  const a=cache.get('Same.','voice',-15,load),b=cache.get('Same.','voice',-15,load);
  await new Promise(r=>setTimeout(r,0));assert.equal(calls,1);release({audio:'saved'});
  assert.deepEqual(await a,await b);
  const reopened=new AudioCache(read,write);
  assert.deepEqual(await reopened.get('Same.','voice',-15,load),{audio:'saved'});assert.equal(calls,1);
  await reopened.get('Same.','other',-15,async()=>{calls++;return 'other';});assert.equal(calls,2);
  await reopened.get('Same.','voice',-10,async()=>{calls++;return 'faster';});assert.equal(calls,3);
});
test('failed requests wait for explicit retry',async()=>{
  let calls=0;const cache=new AudioCache(async()=>null,async()=>{}),load=async()=>{calls++;throw new Error('failed');};
  await assert.rejects(cache.get('a','v',0,load));await assert.rejects(cache.get('a','v',0,load));assert.equal(calls,1);
  cache.retryFailed();await assert.rejects(cache.get('a','v',0,load));assert.equal(calls,2);
});

test('unavailable persistent storage retains audio in memory without duplicate requests',async()=>{
  let calls=0;
  const unavailable=async()=>{throw new Error('Storage disabled');};
  const cache=new AudioCache(unavailable,unavailable);
  const load=async()=>{calls++;return {audio:'once'};};
  assert.deepEqual(await cache.get('sentence','voice',-15,load),{audio:'once'});
  assert.match(cache.warning,/only for this session/);
  assert.deepEqual(await cache.get('sentence','voice',-15,load),{audio:'once'});
  assert.equal(calls,1);
});

test('memory eviction keeps persisted speech reusable without synthesis',async()=>{
  const disk=new Map();let calls=0;
  const cache=new AudioCache(async key=>disk.get(key),async(key,value)=>disk.set(key,value));
  const load=async()=>{calls++;return {audio:'saved'};};
  for(let i=0;i<35;i++)await cache.get(String(i),'voice',-15,load);
  assert.ok(cache.entries.size<=32);
  await cache.get('0','voice',-15,load);
  assert.equal(calls,35);
});
test('batch bridge does not supersede requests and accepts out-of-order results',async()=>{
  const sent=[],rpc=new SpeechRPC(value=>sent.push(value));
  const jobs=[0,1,2,3].map(i=>rpc.request('speech',{text:String(i)}));
  let batch=sent.at(-1);assert.equal(batch.requests.length,3);
  const ids=batch.requests.map(r=>r.id);
  rpc.receive({replies:[{id:ids[1],status:'ready',result:'one'}]});assert.equal(await jobs[1],'one');
  batch=sent.at(-1);assert.deepEqual(batch.requests.map(r=>r.text),['0','2','3']);
  const fourth=batch.requests[2].id;
  rpc.receive({replies:[{id:ids[0],status:'ready',result:'zero'},{id:ids[2],status:'ready',result:'two'},{id:fourth,status:'ready',result:'three'}]});
  assert.deepEqual(await Promise.all(jobs),['zero','one','two','three']);assert.equal(rpc.pending.size,0);
});

test('seek cancels unsent jobs but lets transmitted speech finish into the cache',async()=>{
  const sent=[],rpc=new SpeechRPC(value=>sent.push(value),1);
  const first=new AbortController(),second=new AbortController();
  const running=rpc.request('speech',{text:'current'},first.signal,undefined,true);
  const queued=rpc.request('speech',{text:'queued'},second.signal,undefined,true);
  const rejected=assert.rejects(queued,{name:'AbortError'});
  second.abort();first.abort();await rejected;
  assert.ok(sent.every(command=>command.requests.every(r=>r.text==='current')));
  const id=sent.at(-1).requests[0].id;
  rpc.receive({replies:[{id,status:'ready',result:'audio'}]});
  assert.equal(await running,'audio');
});
