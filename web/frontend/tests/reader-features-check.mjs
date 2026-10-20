// Optional live integration check: invented text only, muted playback.
import {chromium,expect} from '@playwright/test';
import {zipSync,strToU8} from 'fflate';
import assert from 'node:assert/strict';
import {existsSync,mkdirSync} from 'node:fs';

const files={
  'mimetype':'application/epub+zip',
  'META-INF/container.xml':'<container><rootfiles><rootfile full-path="book/package.opf"/></rootfiles></container>',
  'book/package.opf':'<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>Reader feature test</dc:title><dc:language>en</dc:language></metadata><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="a"/><itemref idref="b"/></spine></package>',
  'book/a.xhtml':'<html><body><p>The quiet garden has a small fountain (Smith et al., 2021).</p><p>This invented sentence contains a reference [12] that can be skipped.</p><p>A marked footnote<sup><a epub:type="noteref" href="b.xhtml#note">1</a></sup> stays visible while the voice continues.</p></body></html>',
  'book/b.xhtml':'<html><body><p>Im 17. Jahrhundert entstand ein kleines Dorf.</p><p>Matthew C. Perry wrote a beautiful sentence.</p><p id="note">The search target appears in this later section.</p></body></html>',
};
const book=Buffer.from(zipSync(Object.fromEntries(Object.entries(files).map(([key,value])=>[key,strToU8(value)]))));
const browser=await chromium.launch({channel:'chrome',headless:true,args:['--mute-audio']});
mkdirSync('test-output',{recursive:true});
const saved=existsSync('test-output/reader-browser-state.json');
const context=await browser.newContext({viewport:{width:1280,height:920},...(saved?{storageState:'test-output/reader-browser-state.json'}:{})});
const page=await context.newPage(), errors=[];
page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>{
  window.__requests=new Map();window.__audio=[];
  window.addEventListener('message',event=>{
    if(event.data?.type==='streamlit:setComponentValue') for(const request of event.data.value?.requests || []) {
      if(request.action==='speech'&&!window.__requests.has(request.id))window.__requests.set(request.id,{...request,at:performance.now()});
    }
  });
  const play=HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play=function(){
    window.__audio.push({event:'play',at:performance.now()});
    this.addEventListener('ended',()=>window.__audio.push({event:'ended',at:performance.now()}),{once:true});
    return play.call(this);
  };
});
try {
  await page.goto(process.env.YAPBOOK_TEST_URL || 'http://127.0.0.1:8512/');
  const app=page.frameLocator('iframe[title="streamlit_app.yapbook_reader"]');
  await app.locator('input[type=file]').setInputFiles({name:'features.epub',mimeType:'application/epub+zip',buffer:book});
  const reader=app.frameLocator('iframe[title="EPUB text"]');
  await reader.locator('#section-1').waitFor();
  if(!saved)await expect(app.getByRole('checkbox',{name:'Read citations'})).toBeChecked();
  await app.getByRole('checkbox',{name:'Read citations'}).uncheck();
  await app.getByRole('slider',{name:'Volume',exact:true}).fill('0');
  await reader.locator('body').evaluate(element=>{element.tabIndex=0;element.focus();});
  await page.keyboard.press('Control+f');
  await app.getByRole('textbox',{name:'Search book',exact:true}).fill('search target');
  await app.locator('.search-result button').click();
  await expect(app.getByRole('combobox',{name:'Section',exact:true})).toHaveValue('1');
  assert.equal(await reader.locator('body').evaluate(()=>[...CSS.highlights.get('search')][0].toString()),'search target');
  await app.getByRole('button',{name:'Close panel'}).click();
  await app.getByRole('combobox',{name:'Section',exact:true}).selectOption('0');
  await app.getByRole('button',{name:'Play',exact:true}).click();
  // No further input until the whole book has finished.
  await expect(app.locator('.status')).toContainText('Book finished',{timeout:150000});
  const requests=await page.evaluate(()=>[...window.__requests.values()]);
  assert.ok(requests.length<=6,'At most one request per distinct spoken sentence, with persisted test audio reused.');
  assert.equal(new Set(requests.map(r=>r.text)).size,requests.length,'No identical speech requests.');
  assert.ok(requests.every(r=>!r.text.includes('2021')&&!r.text.includes('[12]')&&!r.text.includes('footnote1')));
  if(!saved){assert.ok(requests.some(r=>r.text==='Im 17. Jahrhundert entstand ein kleines Dorf.'));
    assert.ok(requests.some(r=>r.text==='Matthew C. Perry wrote a beautiful sentence.'));}
  assert.equal(await reader.locator('a[data-reader-citation]').textContent(),'1');
  assert.ok((await reader.locator('body').textContent()).includes('Smith et al., 2021'));
  const timing=await app.locator('body').evaluate(()=>window.__audio);
  const gaps=[];for(let i=1;i<timing.length;i++)if(timing[i].event==='play'&&timing[i-1].event==='ended')gaps.push(Math.round(timing[i].at-timing[i-1].at));
  console.log('Automatic sentence transition gaps (ms):',gaps,'New speech requests:',requests.length);assert.equal(gaps.length,5);
  // A fresh page must reuse IndexedDB audio, with no new speech request.
  await page.reload();
  await app.getByRole('button',{name:'Your library',exact:true}).click();
  await app.locator('.library-item').getByRole('button').first().click();
  await reader.locator('#section-1').waitFor();
  await expect(app.getByRole('checkbox',{name:'Read citations'})).not.toBeChecked();
  await app.getByRole('combobox',{name:'Section',exact:true}).selectOption('0');
  await app.getByRole('button',{name:'Play',exact:true}).click();
  await expect(app.locator('.status')).toContainText('Reading',{timeout:10000});
  await app.getByRole('button',{name:'Pause',exact:true}).click();
  await page.waitForTimeout(1000);
  assert.equal(await page.evaluate(()=>window.__requests.size),0,'Reloaded audio must not be requested again.');
  if(await app.getByRole('button',{name:'Switch to dark mode'}).count())await app.getByRole('button',{name:'Switch to dark mode'}).click();
  await app.getByRole('button',{name:'Search book (Ctrl+F)'}).click();
  await app.getByRole('textbox',{name:'Search book',exact:true}).fill('reference [12]');
  await expect(app.locator('.search-result')).toHaveCount(1);
  await expect.poll(()=>reader.locator('body').evaluate(()=>{const box=[...CSS.highlights.get('spoken')][0].getBoundingClientRect();return box.top>=0&&box.bottom<=innerHeight;})).toBe(true);
  await page.screenshot({path:'tests/reader-features-dark.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForTimeout(300);
  assert.ok(await app.locator('body').evaluate(()=>document.body.scrollWidth<=innerWidth),'No mobile horizontal overflow');
  assert.deepEqual(errors,[]);
  console.log('PASS: full-book search, citation toggle, original markup, continuous playback, six unique requests, reload cache, dark and mobile UI.');
} catch(error) {
  await page.screenshot({path:'tests/reader-features-failure.png',fullPage:true});
  console.log('Browser errors:',errors);throw error;
} finally {await context.storageState({path:'test-output/reader-browser-state.json',indexedDB:true});await browser.close();}
