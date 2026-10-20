import {chromium} from '@playwright/test';
import {readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const workerFile=(await readdir('dist/assets')).find(name=>name.startsWith('kokoro.worker-'));
const browser=await chromium.launchPersistentContext(join(tmpdir(),'yapbook-kokoro-gpu-check-profile'),{channel:'chrome',headless:true});
try {
  const page=await browser.newPage();page.setDefaultTimeout(600000);
  page.on('console',message=>{if(message.type()==='error')console.error(message.text());});
  await page.exposeFunction('reportKokoro',message=>console.log(message));
  await page.goto('http://127.0.0.1:4181/');
  const result=await page.evaluate(async workerFile=>{
    const adapter=await navigator.gpu?.requestAdapter({powerPreference:'high-performance'});
    if(!adapter)return {available:false};
    const info=adapter.info;
    await window.reportKokoro(JSON.stringify({vendor:info.vendor,architecture:info.architecture,device:info.device,description:info.description}));
    const worker=new Worker('/assets/'+workerFile,{type:'module'});let last='';
    try {
      const generate=(id,text)=>new Promise((resolve,reject)=>{
        worker.onerror=event=>reject(new Error(event.message));
        worker.onmessage=event=>{
          const message=event.data;
          if(message.type==='error')reject(new Error(message.error));
          else if(message.type==='ready')resolve({available:true,duration:message.duration,bytes:message.blob.size,type:message.blob.type,gpu:message.gpu});
          else if(message.progress.message!==last){last=message.progress.message;window.reportKokoro(last);}
        };
        worker.postMessage({id,text,voice:'af_heart',speed:1});
      });
      const short=await generate(1,'A quiet library makes room for one more chapter. The reader keeps each sentence close at hand.');
      const long=await generate(2,'The library stood at the end of a narrow street, where every afternoon the windows caught the last of the sunlight. A visitor opened a book and began to read about distant islands, patient explorers, and the maps they carried across the sea. Each page held another detail, from the small tools packed into wooden boxes to the notes written beside a flickering lamp. Outside, the evening grew quiet, but the story continued across several paragraphs and gave the listener a moment to imagine a very different place.');
      return {short,long};
    }finally{worker.terminate();}
  },workerFile);
  console.log(JSON.stringify(result));
  if(!result.short?.available || result.short.duration<1 || result.long?.duration<15 || result.long.bytes<10000)process.exitCode=1;
}finally{await browser.close();}
