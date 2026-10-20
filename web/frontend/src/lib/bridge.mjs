import { Streamlit } from 'streamlit-component-lib';
import { alignBoundaries } from './text.mjs';
import { AudioCache } from './audio-cache.mjs';
import { getSpeech, putSpeech } from './storage.mjs';
import { SpeechRPC } from './rpc.mjs';
import {KokoroClient} from './kokoro.mjs';
import {KOKORO_CACHE} from './kokoro-config.mjs';
const kokoro = new KokoroClient();
export const disposeLocalSpeech = () => kokoro.dispose();

const rpc = new SpeechRPC(command => Streamlit.setComponentValue(command));
export const speechCache = new AudioCache(getSpeech, putSpeech);
Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, event => {
  rpc.receive(event.detail.args.reply);
});
Streamlit.setComponentReady();
export function resizeFrame() {
  let height = window.innerHeight || 850;
  try { height = window.parent.innerHeight; } catch { /* Cross-origin embedding uses the current frame size. */ }
  Streamlit.setFrameHeight(Math.max(640, height));
}
export function request(action, fields = {}, signal, progress, cancelQueuedOnly=false) {
  return rpc.request(action,fields,signal,progress,cancelQueuedOnly);
}
export async function loadAudio(part, voice, rate, signal, progress, engine = 'edge') {
  signal?.throwIfAborted();
  const text=part.speech?.text ?? part.text;
  // The shared request finishes even if this playback consumer stops or seeks.
  let result;
  for(;;) {
    try {
      result=await speechCache.get(text,voice,engine==='kokoro'?rate:rate-15,()=>engine==='kokoro'
        ? kokoro.generate(text,voice,rate,signal,progress)
        : request('speech',{text,voice,rate:rate-15},signal,progress,true),engine==='kokoro'?KOKORO_CACHE:'edge');
      break;
    } catch(error) {
      // A previous consumer may cancel before transmission. Active consumers
      // can schedule it again; a sent request is never cancelled this way.
      if(error.name!=='AbortError' || signal?.aborted)throw error;
    }
  }
  signal?.throwIfAborted();
  const blob=engine==='kokoro'?result.blob:new Blob([Uint8Array.from(atob(result.audio), letter => letter.charCodeAt(0))],{type:'audio/mpeg'});
  let cues=engine==='kokoro'?[{start:0,end:text.length,time:0,until:result.duration}]:alignBoundaries(text,result.boundaries);
  if(part.speech) cues=cues.map(cue=>({...cue,start:part.speech.offsets[cue.start],end:part.speech.offsets[cue.end-1]+1}));
  return {blob,cues};
}
