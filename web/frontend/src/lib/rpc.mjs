// Streamlit can coalesce rapid updates. Every message contains all active jobs.
export class SpeechRPC {
  constructor(send, limit=3, timeout=135000) {
    this.send=send; this.limit=limit; this.timeout=timeout;
    this.pending=new Map(); this.acknowledged=new Set();
  }
  flush() {
    const active=[...this.pending.values()].slice(0,this.limit);
    for(const job of active) if(!job.timer) job.timer=setTimeout(()=>{
      this.pending.delete(job.request.id); this.acknowledged.add(job.request.id);
      job.reject(new Error('The connection timed out. Please retry.')); this.flush();
    },this.timeout);
    this.send({action:'batch',requests:active.map(job=>job.request),ack:[...this.acknowledged]});
  }
  receive(response) {
    for(const id of response?.acked || []) this.acknowledged.delete(id);
    let changed=false;
    for(const reply of response?.replies || []) {
      const job=this.pending.get(reply.id);
      if(!job) continue;
      if(reply.status==='ready' || reply.status==='error') {
        this.pending.delete(reply.id); this.acknowledged.add(reply.id); changed=true;
        if(reply.status==='ready') job.resolve(reply.result);
        else job.reject(new Error(reply.error));
      } else job.progress?.(reply.bytes || 0);
    }
    if(changed) this.flush();
  }
  request(action, fields={}, signal, progress, cancelQueuedOnly=false) {
    signal?.throwIfAborted();
    const id=crypto.randomUUID();
    return new Promise((resolve,reject)=>{
      const cleanup=()=>{clearTimeout(job.timer);signal?.removeEventListener('abort',abort);};
      const abort=()=>{
        if(cancelQueuedOnly && job.timer)return;
        this.pending.delete(id); this.acknowledged.add(id);
        job.reject(new DOMException('Cancelled','AbortError')); this.flush();
      };
      const job={request:{id,action,...fields},progress,
        resolve:value=>{cleanup();resolve(value);},reject:error=>{cleanup();reject(error);}};
      this.pending.set(id,job);signal?.addEventListener('abort',abort,{once:true});this.flush();
    });
  }
}
