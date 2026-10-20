export const KOKORO_ENGINE = 'kokoro';
export const KOKORO_MODEL = 'onnx-community/Kokoro-82M-v1.0-ONNX';
export const KOKORO_CACHE = 'kokoro-js:1.2.1:Kokoro-82M-v1.0:fp32';
export const KOKORO_VOICES = [
  'af_heart','af_alloy','af_aoede','af_bella','af_jessica','af_kore','af_nicole','af_nova','af_river','af_sarah','af_sky',
  'am_adam','am_echo','am_eric','am_fenrir','am_liam','am_michael','am_onyx','am_puck','am_santa',
  'bf_alice','bf_emma','bf_isabella','bf_lily','bm_daniel','bm_fable','bm_george','bm_lewis',
].map(name => ({name,locale:name[0]==='a'?'en-US':'en-GB',gender:name[1]==='f'?'Female':'Male',label:name.slice(3).replace(/^./,letter=>letter.toUpperCase())}));
export const isKokoroVoice = name => KOKORO_VOICES.some(voice=>voice.name===name);
export function selectEngine(settings, engine) {
  const current=settings.engine==='kokoro'?'kokoro':'edge';
  const edgeVoice=current==='edge'?settings.voice:settings.edgeVoice || 'en-US-BrianMultilingualNeural';
  const kokoroVoice=current==='kokoro'?settings.voice:settings.kokoroVoice || 'af_heart';
  return {...settings,engine,edgeVoice,kokoroVoice,voice:engine==='kokoro'?kokoroVoice:edgeVoice};
}
export function kokoroSpeed(rate) {
  if(!Number.isFinite(rate) || rate < -50 || rate > 100)throw new Error('Kokoro speed must be between -50% and +100%.');
  return (100 + rate) / 100;
}
export function kokoroChunks(text, limit=180) {
  const chunks=[];
  let remaining=text.trim();
  while(remaining.length>limit) {
    let end=remaining.lastIndexOf(' ',limit);
    if(end<limit/2)end=limit;
    if(/[\uD800-\uDBFF]/.test(remaining[end-1]))end--;
    chunks.push(remaining.slice(0,end));remaining=remaining.slice(end).trimStart();
  }
  if(remaining)chunks.push(remaining);
  return chunks;
}


export async function requireWebGPU(gpu) {
  if(!gpu)throw new Error('Kokoro needs WebGPU. Use a recent Chrome or Edge browser with graphics acceleration enabled, or switch to online voices.');
  const adapter=await gpu.requestAdapter({powerPreference:'high-performance'});
  if(!adapter || adapter.isFallbackAdapter || adapter.info?.isFallbackAdapter)throw new Error('No compatible GPU is available for Kokoro. Enable graphics acceleration or switch to online voices.');
  return adapter;
}
