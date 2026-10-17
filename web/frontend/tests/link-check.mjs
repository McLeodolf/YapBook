import {chromium} from '@playwright/test';
import {zipSync,strToU8} from 'fflate';
import assert from 'node:assert/strict';

const archive = {
  'META-INF/container.xml': '<container><rootfiles><rootfile full-path="book/package.opf"/></rootfiles></container>',
  'book/package.opf': '<package><metadata><title>Link test</title><language>en</language></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>',
  'book/one.xhtml': '<html><body id="start"><h1>First chapter</h1><p id="origin">Original sentence.</p><p><a href="two.xhtml#note"><strong>Read the note</strong></a></p><p><a href="two.xhtml">Open second chapter</a></p><p><a href="two.xhtml#legacy%20note">Named anchor</a></p><p><a href="two.xhtml#absent">Missing target</a></p><p><a href="https://example.invalid/#note">External link</a></p></body></html>',
  'book/two.xhtml': '<html><body><h1>Second chapter</h1>' + '<p>Filler text to place the note below the fold.</p>'.repeat(20) + '<p id="note">Here is the note.</p><p><a href="one.xhtml#origin">Return to the beginning</a></p><p><a href="one.xhtml#start">Return to the body anchor</a></p><p><a name="legacy note"></a>Legacy note text.</p><p><a href="#note">Same chapter link</a></p></body></html>'
};
const book = Buffer.from(zipSync(Object.fromEntries(Object.entries(archive).map(([key,value]) => [key,strToU8(value)]))));
const browser = await chromium.launch({channel:'chrome',headless:true,args:['--mute-audio']});
const page = await browser.newPage({viewport:{width:1100,height:850}});
const errors=[]; page.on('pageerror',error=>errors.push(error.message));
await page.addInitScript(()=>{window.__speech=[];window.addEventListener('message',event=>{if(event.data?.type==='streamlit:setComponentValue'&&event.data.value?.action==='speech')window.__speech.push(event.data.value.text);});});
try {
  await page.goto(process.env.YAPBOOK_TEST_URL || 'http://127.0.0.1:8501/');
  const app = page.frameLocator('iframe[title="streamlit_app.yapbook_reader"]');
  await app.locator('input[type=file]').setInputFiles({name:'links.epub',mimeType:'application/epub+zip',buffer:book});
  const reader = app.frameLocator('iframe[title="EPUB text"]');
  await reader.getByRole('heading',{name:'First chapter'}).waitFor();
  const original = await reader.locator('body').evaluate(()=>({url:location.href,text:document.body.textContent}));
  await reader.getByRole('link',{name:'Read the note'}).click();
  await page.waitForTimeout(500);
  const after = await app.locator('iframe[title="EPUB text"]').evaluate(frame=>({url:frame.contentDocument?.URL,sections:frame.contentDocument?.querySelectorAll('.book-section').length}));
  console.log('Frame after hyperlink:',after);
  assert.equal(after.sections,2,'Link must keep the complete book document loaded.');
  assert.equal(after.url,original.url,'Link must not navigate the srcdoc iframe.');
  const checkTarget = async text => {
    await app.getByRole('button',{name:'Pause',exact:true}).click();
    await page.waitForTimeout(400);
    assert.equal(await reader.locator('body').evaluate(()=>[...CSS.highlights.get('spoken')][0].toString()),text);
    const bounds=await reader.locator('body').evaluate(()=>{const box=[...CSS.highlights.get('spoken')][0].getBoundingClientRect();return {top:box.top,bottom:box.bottom,height:innerHeight};});
    assert.ok(bounds.top>=0&&bounds.bottom<=bounds.height,'Link destination should be visible.');
  };
  await checkTarget('Here is the note.');
  assert.equal(await app.getByRole('combobox',{name:'Section',exact:true}).inputValue(),'1');
  assert.equal((await page.evaluate(()=>window.__speech))[0],'Here is the note.','The destination is read, not the link label.');
  await reader.getByRole('link',{name:'Return to the beginning'}).click();
  await checkTarget('Original sentence.');
  await app.getByRole('button',{name:'Follow current sentence'}).click();
  await reader.getByRole('link',{name:'Open second chapter'}).click();
  await checkTarget('Second chapter');
  await reader.getByRole('link',{name:'Return to the body anchor'}).click();
  await checkTarget('First chapter');
  await reader.getByRole('link',{name:'Named anchor'}).click();
  await checkTarget('Legacy note text.');
  await reader.getByRole('link',{name:'Same chapter link'}).focus();
  await page.keyboard.press('Enter');
  await checkTarget('Here is the note.');
  await reader.getByRole('link',{name:'Missing target'}).click();
  assert.equal(await reader.locator('.book-section').count(),2);
  assert.equal(await reader.locator('body').textContent(),original.text);
  assert.equal(await reader.locator('a').filter({hasText:'External link'}).getAttribute('href'),null);
  assert.deepEqual(errors,[]);
  console.log('PASS: internal links start reading at the destination; cross-section, body, named, keyboard and missing-target links keep the book intact.');
} finally { await browser.close(); }
