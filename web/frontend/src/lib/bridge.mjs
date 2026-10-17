import { Streamlit } from 'streamlit-component-lib';
import { alignBoundaries } from './text.mjs';

let pending;
Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, event => {
  const reply = event.detail.args.reply;
  if (!pending || reply?.id !== pending.id) return;
  if (reply.status === 'ready') {
    Streamlit.setComponentValue({id:reply.id,action:'ack'});
    pending.resolve(reply.result);
  }
  else if (reply.status === 'error') pending.reject(new Error(reply.error));
  else pending.progress?.(reply.bytes || 0);
});
Streamlit.setComponentReady();
export function resizeFrame() {
  let height = window.innerHeight || 850;
  try { height = window.parent.innerHeight; } catch { /* Cross-origin embedding uses the current frame size. */ }
  Streamlit.setFrameHeight(Math.max(640, height));
}
export function request(action, fields = {}, signal, progress) {
  if (pending) pending.reject(new DOMException('Superseded', 'AbortError'));
  const id = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    let timer;
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); if (pending?.id === id) pending = null; };
    const abort = () => {
      if (pending?.id === id) Streamlit.setComponentValue({id: crypto.randomUUID(), action: 'cancel'});
      cleanup(); reject(new DOMException('Cancelled', 'AbortError'));
    };
    pending = {id, progress, resolve: value => { cleanup(); resolve(value); }, reject: error => { cleanup(); reject(error); }};
    if (signal?.aborted) { abort(); return; }
    signal?.addEventListener('abort', abort, {once: true});
    timer = setTimeout(() => { if (pending?.id === id) { Streamlit.setComponentValue({id:crypto.randomUUID(),action:'cancel'}); pending.reject(new Error('The connection timed out. Please retry.')); } }, 100000);
    Streamlit.setComponentValue({ id, action, ...fields });
  });
}
export async function loadAudio(part, voice, rate, signal, progress) {
  const result = await request('speech', {text:part.text, voice, rate:rate - 15}, signal, progress);
  signal.throwIfAborted();
  const bytes = Uint8Array.from(atob(result.audio), letter => letter.charCodeAt(0));
  return {blob:new Blob([bytes], {type:'audio/mpeg'}), cues:alignBoundaries(part.text, result.boundaries)};
}
