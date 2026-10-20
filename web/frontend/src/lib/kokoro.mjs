import {isKokoroVoice,kokoroSpeed} from './kokoro-config.mjs';

// Only one graph executes at a time; cancelled queued jobs never reach the GPU.
// Started jobs finish into the shared cache, even if their playback listener leaves.
export class KokoroClient {
  constructor(createWorker=()=>new Worker(new URL('./kokoro.worker.mjs',import.meta.url),{type:'module'})) {
    this.createWorker=createWorker;this.pending=[];this.active=null;this.sequence=0;this.worker=null;
  }
  generate(text,voice,rate,signal,progress) {
    signal?.throwIfAborted();
    if(!isKokoroVoice(voice))return Promise.reject(new Error('Choose an English Kokoro voice.'));
    return new Promise((resolve,reject)=>{
      const job={id:++this.sequence,text,voice,speed:kokoroSpeed(rate),resolve,reject,progress,signal};
      job.cancel=()=>{
        const index=this.pending.indexOf(job);
        if(index>=0){this.pending.splice(index,1);reject(new DOMException('Cancelled','AbortError'));}
      };
      signal?.addEventListener('abort',job.cancel,{once:true});
      this.pending.push(job);this.pump();
    });
  }
  pump() {
    if(this.active || !this.pending.length)return;
    const job=this.active=this.pending.shift();
    job.signal?.removeEventListener('abort',job.cancel);
    try {
      if(!this.worker) {
        this.worker=this.createWorker();
        this.worker.onmessage=event=>this.receive(event.data);
        this.worker.onerror=()=>this.fail(new Error('Kokoro could not start in this browser. Enable graphics acceleration or switch to online voices.'));
      }
      this.timer=setTimeout(()=>this.fail(new Error('Kokoro took too long to respond. Check the model download or switch to online voices.')),600000);
      job.progress?.({stage:'loading',message:'Loading Kokoro on your GPU…'});
      this.worker.postMessage({id:job.id,text:job.text,voice:job.voice,speed:job.speed});
    }catch(error){this.fail(error);}
  }
  receive(message) {
    const job=this.active;
    if(!job || job.id!==message.id)return;
    if(message.type==='progress'){job.progress?.(message.progress);return;}
    if(message.type!=='ready'){this.fail(new Error(message.error || 'Kokoro could not generate this sentence.'));return;}
    clearTimeout(this.timer);this.active=null;
    job.resolve({blob:message.blob,duration:message.duration});this.pump();
  }
  fail(error) {
    clearTimeout(this.timer);this.worker?.terminate();this.worker=null;
    this.active?.reject(error);this.active=null;
    for(const job of this.pending){job.signal?.removeEventListener('abort',job.cancel);job.reject(error);}
    this.pending=[];
  }
  dispose(){this.fail(new DOMException('Cancelled','AbortError'));}
}
