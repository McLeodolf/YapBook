import test from 'node:test';
import assert from 'node:assert/strict';
import {KokoroClient} from '../src/lib/kokoro.mjs';
import {KOKORO_CACHE,KOKORO_VOICES,selectEngine,kokoroSpeed,kokoroChunks,requireWebGPU} from '../src/lib/kokoro-config.mjs';
import {generateAudio} from '../src/lib/kokoro.worker.mjs';
import {AudioCache} from '../src/lib/audio-cache.mjs';
import {readSettings,saveSettings} from '../src/lib/storage.mjs';

function fixture() {
  const sent=[];let created=0,terminated=0;
  const worker={postMessage:value=>sent.push(value),terminate:()=>terminated++};
  const client=new KokoroClient(()=>{created++;return worker;});
  return {client,worker,sent,get created(){return created;},get terminated(){return terminated;},reply:message=>worker.onmessage({data:message})};
}

test('WebGPU is mandatory and software fallback adapters are rejected',async()=>{
  await assert.rejects(requireWebGPU(undefined),/needs WebGPU/);
  await assert.rejects(requireWebGPU({requestAdapter:async()=>null}),/No compatible GPU/);
  await assert.rejects(requireWebGPU({requestAdapter:async()=>({info:{isFallbackAdapter:true}})}),/No compatible GPU/);
  const adapter={info:{vendor:'test'}};assert.equal(await requireWebGPU({requestAdapter:async options=>{assert.equal(options.powerPreference,'high-performance');return adapter;}}),adapter);
});

test('Kokoro is lazy, serializes six prepared jobs and preserves default speed',async()=>{
  const f=fixture();assert.equal(f.created,0);
  const progress=[],jobs=Array.from({length:6},(_,i)=>f.client.generate(`Sentence ${i}.`,'af_heart',0,undefined,p=>progress.push(p.message)));
  assert.equal(f.created,1);assert.equal(f.sent.length,1);assert.equal(f.sent[0].speed,1);
  f.reply({id:1,type:'progress',progress:{message:'Downloading model'}});assert.ok(progress.includes('Downloading model'));
  for(let i=0;i<6;i++){
    assert.equal(f.sent.length,i+1);assert.equal(f.sent[i].text,`Sentence ${i}.`);
    f.reply({id:i+1,type:'ready',blob:new Blob(['audio']),duration:1});assert.equal((await jobs[i]).duration,1);
  }
  f.client.dispose();assert.equal(f.terminated,1);
});

test('cancellation removes unsent GPU jobs while active inference completes once',async()=>{
  const f=fixture(),first=new AbortController(),second=new AbortController();
  const a=f.client.generate('First.','af_heart',0,first.signal),b=f.client.generate('Second.','af_heart',0,second.signal);
  const cancelled=assert.rejects(b,{name:'AbortError'});first.abort();second.abort();await cancelled;
  f.reply({id:1,type:'ready',blob:new Blob(['ready']),duration:2});assert.equal((await a).duration,2);
  assert.equal(f.sent.length,1);f.client.dispose();
});

test('worker startup failures reject every queued job without any online fallback',async()=>{
  const f=fixture();
  const jobs=[f.client.generate('First.','af_heart',0),f.client.generate('Second.','af_heart',0)];
  const rejected=jobs.map(job=>assert.rejects(job,/could not start/));f.worker.onerror();await Promise.all(rejected);
  assert.equal(f.sent.length,1);assert.equal(f.terminated,1);
});

test('engine cache namespaces reuse successful local audio without online collisions',async()=>{
  const disk=new Map(),cache=new AudioCache(async key=>disk.get(key),async(key,value)=>disk.set(key,value));let calls=0;
  const load=async()=>({value:++calls});
  assert.deepEqual(await cache.get('Same.','af_heart',-15,load,'edge'),{value:1});
  assert.deepEqual(await cache.get('Same.','af_heart',-15,load,KOKORO_CACHE),{value:2});
  assert.deepEqual(await cache.get('Same.','af_heart',-15,load,KOKORO_CACHE),{value:2});
  await Promise.all([...cache.entries.values()].map(entry=>entry.persisted));
  const reopened=new AudioCache(async key=>disk.get(key),async()=>{});
  assert.deepEqual(await reopened.get('Same.','af_heart',-15,load,KOKORO_CACHE),{value:2});assert.equal(calls,2);
});

test('engine preferences retain each voice and favorites across reloads',()=>{
  let saved='{}';globalThis.localStorage={getItem:()=>saved,setItem:(key,value)=>{saved=value;}};
  let settings=readSettings();assert.equal(settings.engine,'edge');
  settings.voice='de-DE-KatjaNeural';settings=selectEngine(settings,'kokoro');assert.equal(settings.voice,'af_heart');
  settings.voice='bf_emma';settings.favorites=['de-DE-KatjaNeural','bf_emma'];saveSettings(settings);
  settings=readSettings();assert.equal(settings.voice,'bf_emma');assert.deepEqual(settings.favorites,['de-DE-KatjaNeural','bf_emma']);
  settings=selectEngine(settings,'edge');assert.equal(settings.voice,'de-DE-KatjaNeural');
  assert.equal(selectEngine(settings,'kokoro').voice,'bf_emma');assert.ok(KOKORO_VOICES.every(voice=>voice.locale.startsWith('en-')));
  delete globalThis.localStorage;
});

test('long Kokoro inputs split without dropped text or broken Unicode',()=>{
  const text=('A long sentence with dates 2025 and punctuation, plus a book 📖. ').repeat(20).trim();
  const chunks=kokoroChunks(text);assert.ok(chunks.length>1);assert.ok(chunks.every(chunk=>chunk.length<=180));
  assert.equal(chunks.join(' '),text);assert.equal(kokoroSpeed(-50),0.5);assert.throws(()=>kokoroSpeed(-55),/speed must be/);assert.equal(kokoroSpeed(100),2);assert.equal(kokoroSpeed(0),1);
});

test('GPU sentence stream closes, joins all chunks and rejects silent phoneme truncation',async()=>{
  class Splitter {push(text){this.text=text;}close(){this.closed=true;}}
  let generated=0;
  const model={tokenizer:()=>({input_ids:{dims:[1,40]}}),async *stream(splitter,settings){
    assert.equal(splitter.closed,true,'An open Kokoro stream never completes');assert.equal(settings.speed,0.85);
    generated++;yield {phonemes:splitter.text,audio:{audio:new Float32Array(24000).fill(0.25)}};
  }};
  const text=('One long invented passage has enough words to need careful chunking. ').repeat(8);
  const result=await generateAudio(model,Splitter,text,'af_heart',0.85,()=>{});
  assert.equal(generated,kokoroChunks(text).length);assert.equal(result.duration,generated);assert.equal(result.blob.size,44+48000*generated);
  const view=new DataView(await result.blob.arrayBuffer());assert.equal(view.getUint16(22,true),1);assert.equal(view.getUint32(24,true),24000);
  model.tokenizer=()=>({input_ids:{dims:[1,513]}});
  await assert.rejects(generateAudio(model,Splitter,'Text.','af_heart',0.85,()=>{}),/beyond Kokoro/);
});

test('model setup errors fail the whole GPU queue without automatic repeated setup',async()=>{
  const f=fixture(),jobs=Array.from({length:6},(_,index)=>f.client.generate(`Sentence ${index}.`,'af_heart',0));
  const failed=jobs.map(job=>assert.rejects(job,/No compatible GPU/));
  f.reply({id:1,type:'error',error:'No compatible GPU'});await Promise.all(failed);
  assert.equal(f.sent.length,1);assert.equal(f.terminated,1);assert.equal(f.client.pending.length,0);
});
