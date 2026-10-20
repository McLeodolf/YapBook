import {test as base, expect} from '@playwright/test';
import {zipSync, strToU8} from 'fflate';

function makeBook(body = '<p>Evidence (Smith et al., 2021) supports this [12].</p><p>A second invented sentence.</p><a href="b.xhtml#target">Read the destination</a>') {
  const files = {
    mimetype: 'application/epub+zip',
    'META-INF/container.xml': '<container><rootfiles><rootfile full-path="book/package.opf"/></rootfiles></container>',
    'book/package.opf': '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Reader fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>',
    'book/a.xhtml': '<html><body>' + body + '</body></html>',
    'book/b.xhtml': '<html><body><p id="target">The search destination is in the next section.</p><p>Matthew C. Perry visited in the 17. Jahrhundert.</p></body></html>',
  };
  return Buffer.from(zipSync(Object.fromEntries(Object.entries(files).map(([name, text]) => [name, strToU8(text)]))));
}

const test = base.extend({
  page: async ({page}, use) => {
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
    });
    await page.addInitScript(() => {
      window.__speech = [];
      window.__audio = [];
      window.__seen = new Map();
      window.__heldSpeech = new Map();
      window.__holdSpeech = false;
      window.__resolveSpeech = text => {
        const request = window.__speech.find(request => request.text === text);
        const reply = window.__heldSpeech.get(request?.id);
        if (!reply) throw new Error('No pending speech for ' + text);
        window.__seen.set(request.id,reply); window.__heldSpeech.delete(request.id);
        window.postMessage({type: 'streamlit:render',args: {reply: {replies: [...window.__seen.values()]}},disabled: false},window.location.origin);
      };
      window.Audio = class extends EventTarget {
        constructor() {super(); this.currentTime = 0; this.volume = 1; this.src = ''; window.__audio.push(this);}
        play() {return Promise.resolve();}
        pause() {}
        load() {}
        removeAttribute(name) {if (name === 'src') this.src = '';}
        getAttribute(name) {return name === 'src' ? this.src : null;}
      };
      window.addEventListener('message', event => {
        if (event.data?.type !== 'streamlit:setComponentValue') return;
        const command = event.data.value;
        for (const id of command?.ack || []) {window.__seen.delete(id);window.__heldSpeech.delete(id);}
        for (const request of command?.requests || []) {
          if (window.__seen.has(request.id)) continue;
          let result;
          if (request.action === 'voices') result = {voices: [{name: 'en-US-BrianMultilingualNeural', locale: 'en-US', gender: 'Male'}]};
          else {
            window.__speech.push(request);
            result = {audio: btoa('synthetic audio boundary'), boundaries: [{text: request.text, offset: 0, duration: 10_000_000}]};
          }
          const reply = {id: request.id, status: 'ready', result};
          if (window.__holdSpeech && request.action === 'speech') {
            window.__heldSpeech.set(request.id,reply);
            window.__seen.set(request.id,{id: request.id,status: 'preparing',bytes: 0});
          } else window.__seen.set(request.id,reply);
        }
        if (window.__seen.size) queueMicrotask(() => window.postMessage({type: 'streamlit:render',
          args: {reply: {replies: [...window.__seen.values()]}}, disabled: false}, window.location.origin));
      });
    });
    await use(page);

  },
});

test('EPUB scripts, event handlers, external resources and active elements cannot escape the reader', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  const hostile = '<h1>A safe heading</h1><script>parent.__pwned=true</script>' +
    '<img src="https://attacker.invalid/pixel" onerror="parent.__pwned=true">' +
    '<a href="javascript:parent.__pwned=true">Bad link</a><iframe src="https://attacker.invalid/"></iframe>' +
    '<form action="https://attacker.invalid/"><input autofocus></form>' +
    '<style>@import "https://attacker.invalid/evil.css";p{position:fixed;background:url(https://attacker.invalid/pixel)}</style>' +
    '<p onclick="parent.__pwned=true">Readable text.</p><a href="b.xhtml#target">Internal link</a>';
  await page.locator('input[type=file]').setInputFiles({name: 'hostile.epub', mimeType: 'application/epub+zip', buffer: makeBook(hostile)});
  const frame = page.frameLocator('iframe[title="EPUB text"]');
  await expect(frame.locator('#section-1')).toBeVisible();
  expect(await frame.locator('script,iframe,form,input,object,embed').count()).toBe(0);
  expect(await frame.locator('body').evaluate(body => [...body.querySelectorAll('*')].some(node => [...node.attributes].some(a => /^on/i.test(a.name))))).toBe(false);
  expect(await frame.locator('img').getAttribute('src')).toBe('');
  expect(await frame.getByText('Bad link').getAttribute('href')).toBeNull();
  expect(await frame.getByText('Internal link').getAttribute('href')).toBe('#s1-target');
  expect(await frame.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content')).toContain("default-src 'none'");
  expect(await page.locator('iframe[title="EPUB text"]').getAttribute('sandbox')).toBe('allow-same-origin');
  expect(await page.evaluate(() => Boolean(window.__pwned))).toBe(false);
  expect(errors).toEqual([]);
});

test('search, citation projection, prefetch, themes and persisted cache work together without a voice service', async ({page}) => {
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles({name: 'fixture.epub', mimeType: 'application/epub+zip', buffer: makeBook()});
  const frame = page.frameLocator('iframe[title="EPUB text"]');
  await expect(frame.locator('#section-1')).toBeVisible();
  await page.getByRole('checkbox', {name: 'Read citations'}).uncheck();
  await page.getByRole('button', {name: 'Play', exact: true}).click();
  await expect(page.locator('.status')).toContainText('Reading');
  await expect.poll(() => page.evaluate(() => window.__speech.length)).toBe(5);
  expect(await page.evaluate(() => window.__speech[0].text)).toBe('Evidence supports this.');
  await page.getByRole('button', {name: 'Pause', exact: true}).click();
  await page.getByRole('button', {name: 'Search book (Ctrl+F)'}).first().click();
  await page.getByRole('textbox', {name: 'Search book', exact: true}).fill('search destination');
  await page.locator('.search-result button').click();
  await expect(page.getByRole('combobox', {name: 'Section', exact: true})).toHaveValue('1');
  expect(await frame.locator('body').evaluate(() => [...CSS.highlights.get('search')][0].toString())).toBe('search destination');
  await page.getByRole('button', {name: 'Close panel'}).click();
  await page.getByRole('button', {name: 'Switch to dark mode'}).click();
  await expect(frame.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await page.getByRole('button', {name: 'Your library', exact: true}).click();
  await page.locator('.library-item').getByRole('button').first().click();
  await expect(frame.locator('#section-1')).toBeVisible();
  await expect(page.getByRole('checkbox', {name: 'Read citations'})).not.toBeChecked();
  await page.getByRole('combobox', {name: 'Section', exact: true}).selectOption('0');
  await page.getByRole('button', {name: 'Play', exact: true}).click();
  await expect(page.locator('.status')).toContainText('Reading');
  expect(await page.evaluate(() => window.__speech.length)).toBe(0);
});

test('malformed and oversized archives are rejected', async ({page}) => {
  await page.goto('/');
  const errors = await page.evaluate(async () => {
    const {openEpub} = await import('/src/lib/epub.mjs');
    const messages = [];
    for (const blob of [new Blob(['not a zip']), new Blob([new Uint8Array(50 * 1024 * 1024 + 1)])]) {
      try {await openEpub(blob); messages.push('unexpected success');}
      catch (error) {messages.push(error.message);}
    }
    return messages;
  });
  expect(errors).toEqual(['This file is not a readable EPUB archive.', 'Please choose an EPUB smaller than 50 MB.']);
});


test('continuous playback maintains five upcoming sentences and reuses previous audio on backward seeks', async ({page}) => {
  await page.goto('/');
  await page.evaluate(() => {window.__holdSpeech = true;});
  const sentences = Array.from({length: 12},(_,index) => `An invented sentence number ${index + 1}.`);
  await page.locator('input[type=file]').setInputFiles({name: 'buffer.epub',mimeType: 'application/epub+zip',buffer: makeBook(sentences.map(text => `<p>${text}</p>`).join(''))});
  await expect(page.frameLocator('iframe[title="EPUB text"]').locator('#section-1')).toBeVisible();
  await page.getByRole('button', {name: 'Play',exact: true}).click();
  await expect.poll(() => page.evaluate(() => window.__speech.length)).toBe(6);
  expect(await page.evaluate(() => window.__speech.map(request => request.text))).toEqual(sentences.slice(0,6));
  await page.evaluate(texts => {window.__resolveSpeech(texts[5]);window.__resolveSpeech(texts[0]);},sentences);
  await expect(page.locator('.status')).toContainText('Reading');
  await page.evaluate(() => window.__audio[0].onended());
  await expect.poll(() => page.evaluate(() => window.__speech.length)).toBe(7);
  await expect(page.locator('.status')).toContainText('Preparing');
  await page.evaluate(text => window.__resolveSpeech(text),sentences[1]);
  await expect(page.locator('.status')).toContainText('Reading');
  for(let index = 2;index <= 6;index++) {
    if(index !== 5) await page.evaluate(text => window.__resolveSpeech(text),sentences[index]);
    await page.evaluate(() => window.__audio[0].onended());
    await expect.poll(() => page.evaluate(() => window.__speech.length)).toBe(index + 6);
    await expect(page.locator('.status')).toContainText('Reading');
  }
  const frame = page.frameLocator('iframe[title="EPUB text"]');
  await frame.getByText(sentences[1],{exact: true}).click();
  await expect(page.locator('.status')).toContainText('Reading');
  expect(await page.evaluate(() => window.__speech.length)).toBe(12);
  for(let index = 2;index <= 6;index++) {
    await page.evaluate(() => window.__audio[0].onended());
    await expect(page.locator('.status')).toContainText('Reading');
    // The existing source audio changes on every real transition, including cached ones.
    await expect.poll(() => frame.locator('body').evaluate(() => [...CSS.highlights.get('spoken')][0].toString())).toBe(sentences[index]);
  }
  const requested = await page.evaluate(() => window.__speech.map(request => request.text));
  expect(requested).toEqual(sentences);
  expect(new Set(requested).size).toBe(requested.length);
});

test('Kokoro toggle uses a local worker, keeps engine voices and never sends local text to the server',async({page})=>{
  await page.addInitScript(()=>{
    window.__gpu=[];window.__workers=[];window.__gpuHold=false;
    window.Worker=class {
      constructor(){window.__workers.push(this);}
      postMessage(job){
        window.__gpu.push(job);
        this.onmessage({data:{id:job.id,type:'progress',progress:{message:'Downloading Kokoro test model…'}}});
        const complete=()=>this.onmessage?.({data:{id:job.id,type:'ready',blob:new Blob(['local audio'],{type:'audio/wav'}),duration:3}});
        if(window.__gpuHold)window.__completeGPU=complete;else queueMicrotask(complete);
      }
      terminate(){}
    };
  });
  await page.goto('/');
  expect(await page.evaluate(()=>window.__workers.length)).toBe(0);
  await page.getByRole('button',{name:'Switch to Kokoro on your GPU'}).click();
  await expect(page.getByRole('button',{name:'Kokoro GPU active — switch to online voices'})).toHaveAttribute('aria-pressed','true');
  await expect(page.getByRole('combobox',{name:'Reading voice'})).toHaveValue('Heart · Kokoro');
  expect(await page.evaluate(()=>window.__workers.length)).toBe(0);
  await page.getByRole('button',{name:'Favorite voice',exact:true}).click();
  await page.getByRole('button',{name:'Preview voice'}).click();
  await expect(page.locator('.status')).toContainText('Voice preview');
  expect(await page.evaluate(()=>window.__gpu[0].speed)).toBe(1);
  expect(await page.evaluate(()=>window.__speech.length)).toBe(0);
  await page.getByRole('button',{name:'Kokoro GPU active — switch to online voices'}).click();
  await expect(page.locator('.status')).not.toContainText('Voice preview');
  await expect(page.getByRole('combobox',{name:'Reading voice'})).toHaveValue('Brian · Multilingual');
  await page.getByRole('button',{name:'Switch to Kokoro on your GPU'}).click();
  await page.reload();
  await expect(page.getByRole('combobox',{name:'Reading voice'})).toHaveValue('Heart · Kokoro');
  await expect(page.getByRole('button',{name:'Favorite voice',exact:true})).toHaveAttribute('aria-pressed','true');
  expect(await page.evaluate(()=>window.__workers.length)).toBe(0);
  await page.getByRole('button',{name:'Preview voice'}).click();
  await expect(page.locator('.status')).toContainText('Voice preview');
  expect(await page.evaluate(()=>window.__gpu.length)).toBe(0);
  await page.locator('input[type=file]').setInputFiles({name:'local.epub',mimeType:'application/epub+zip',buffer:makeBook()});
  await expect(page.frameLocator('iframe[title="EPUB text"]').locator('#section-1')).toBeVisible();
  await page.getByRole('checkbox',{name:'Read citations'}).uncheck();
  await page.getByRole('button',{name:'Play',exact:true}).click();
  await expect(page.locator('.status')).toContainText('Reading');
  await expect.poll(()=>page.evaluate(()=>window.__gpu.length)).toBe(5);
  expect(await page.evaluate(()=>window.__gpu[0].text)).toBe('Evidence supports this.');
  expect(await page.evaluate(()=>window.__speech.length)).toBe(0);
});

test('switching engines during local preparation cancels playback and unsupported GPU errors stay local',async({page})=>{
  await page.addInitScript(()=>{
    window.__gpu=[];window.__workers=[];window.__gpuError=false;
    window.Worker=class {
      constructor(){window.__workers.push(this);}
      postMessage(job){
        window.__gpu.push(job);
        this.onmessage({data:{id:job.id,type:'progress',progress:{message:'Downloading Kokoro test model…'}}});
        window.__completeGPU=()=>this.onmessage({data:window.__gpuError
          ? {id:job.id,type:'error',error:'Kokoro needs WebGPU. Switch to online voices.'}
          : {id:job.id,type:'ready',blob:new Blob(['local audio']),duration:3}});
      }
      terminate(){}
    };
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Switch to Kokoro on your GPU'}).click();
  await page.getByRole('button',{name:'Dismiss message'}).click();
  await page.getByRole('button',{name:'Preview voice'}).click();
  await expect(page.locator('.status')).toContainText('Downloading Kokoro test model');
  await page.getByRole('button',{name:'Kokoro GPU active — switch to online voices'}).click();
  await page.evaluate(()=>window.__completeGPU());
  await expect(page.locator('.status')).not.toContainText('Voice preview');
  expect(await page.evaluate(()=>window.__speech.length)).toBe(0);
  // A different voice cannot use the successful preview cache from the first request.
  await page.getByRole('button',{name:'Switch to Kokoro on your GPU'}).click();
  await page.getByRole('button',{name:'Dismiss message'}).click();
  await page.getByRole('combobox',{name:'Reading voice'}).fill('bella');
  await page.getByRole('listbox').getByRole('option').first().click();
  await page.evaluate(()=>{window.__gpuError=true;});
  await page.getByRole('button',{name:'Preview voice'}).click();
  await expect.poll(()=>page.evaluate(()=>window.__gpu.length)).toBe(2);
  await page.evaluate(()=>window.__completeGPU());
  await expect(page.getByRole('alert')).toContainText('Kokoro needs WebGPU');
  expect(await page.evaluate(()=>window.__speech.length)).toBe(0);
});
