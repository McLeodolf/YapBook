import {KOKORO_MODEL,kokoroChunks,requireWebGPU} from './kokoro-config.mjs';
let modelPromise, TextSplitter, runtime;
async function loadModel(progress) {
  const adapter=await requireWebGPU(navigator.gpu);
  const {KokoroTTS,TextSplitterStream,env}=await import('kokoro-js');
  const {env:transformersEnv}=await import('@huggingface/transformers');
  runtime=transformersEnv.backends.onnx.webgpu;runtime.adapter=adapter;TextSplitter=TextSplitterStream;
  // Self-host the runtime assets; no CDN script is required at playback time.
  const {default:wasm}=await import('../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.jsep.wasm?url');
  const {default:module}=await import('../../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.jsep.mjs?url');
  env.wasmPaths={wasm,mjs:module};
  return KokoroTTS.from_pretrained(KOKORO_MODEL,{device:'webgpu',dtype:'fp32',progress_callback:event=>{
    const percent=Number.isFinite(event.progress)?Math.round(event.progress):null;
    progress({stage:'loading',message:event.status==='progress'?`Downloading Kokoro${percent===null?'':` · ${percent}%`}…`:'Loading Kokoro on your GPU…'});
  }});
}
function wav(samples,sampleRate) {
  const bytes=new ArrayBuffer(44+samples.length*2),view=new DataView(bytes);
  const write=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};
  write(0,'RIFF');view.setUint32(4,36+samples.length*2,true);write(8,'WAVE');write(12,'fmt ');
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,sampleRate,true);
  view.setUint32(28,sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);write(36,'data');view.setUint32(40,samples.length*2,true);
  for(let i=0;i<samples.length;i++)view.setInt16(44+i*2,Math.max(-1,Math.min(1,samples[i]))*32767,true);
  return new Blob([bytes],{type:'audio/wav'});
}
export async function generateAudio(model,Splitter,text,voice,speed,progress) {
  const chunks=kokoroChunks(text),audio=[];
    for(let index=0;index<chunks.length;index++) {
      progress({stage:'generating',message:`Generating on your GPU${chunks.length>1?` · ${index+1}/${chunks.length}`:''}…`});
      // The library silently truncates oversized phoneme sequences. Validate before
      // accepting any output so an unusual expansion cannot omit the book's text.
      const splitter=new Splitter();splitter.push(chunks[index]);splitter.close();
      for await(const result of model.stream(splitter,{voice,speed})) {
        const tokens=model.tokenizer(result.phonemes,{truncation:false}).input_ids;
        if(tokens.dims.at(-1)>512)throw new Error('This sentence expands beyond Kokoro’s text limit. Choose online voices for this passage.');
        audio.push(result.audio.audio);
      }
    }
    const samples=new Float32Array(audio.reduce((length,part)=>length+part.length,0));let offset=0;
    for(const part of audio){samples.set(part,offset);offset+=part.length;}
    if(!samples.length)throw new Error('Kokoro returned no audio. Please retry or choose another voice.');
  return {blob:wav(samples,24000),duration:samples.length/24000};
}

if(typeof self!=='undefined')self.onmessage=async event=>{
  const {id,text,voice,speed}=event.data;
  const progress=value=>self.postMessage({id,type:'progress',progress:value});
  try {
    modelPromise ??= loadModel(progress).catch(error=>{modelPromise=null;throw error;});
    const model=await modelPromise;
    const audio=await generateAudio(model,TextSplitter,text,voice,speed,progress);
    const device=await runtime.device;
    const info=device.adapterInfo || runtime.adapter.info;
    self.postMessage({id,type:'ready',...audio,gpu:{vendor:info?.vendor,architecture:info?.architecture}});
  }catch(error){self.postMessage({id,type:'error',error:error.message || 'Kokoro could not run on this GPU.'});}
};
