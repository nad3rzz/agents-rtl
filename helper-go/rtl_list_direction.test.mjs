import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import vm from 'node:vm';

function readPart(name) {
  return readFileSync(new URL('./rtl_script_parts/' + name, import.meta.url), 'utf8');
}

const productionFunctions = [
  readPart('00_00_prelude_start.js').replace('(() => {', ''),
  readPart('00_30_webview_selectors.js'), readPart('00_32_agent_text_selectors.js'),
  readPart('00_40_environment_helpers.js').split('\n')[0],
  readPart('20_30_text_helpers.js'), readPart('20_40_apply_text_direction.js'),
  readPart('20_50_restore_text_direction.js'), readPart('20_65_list_direction.js'),
].join('\n');
const listStyleLine = readPart('10_styles.js').split('\n').find(line => line.includes(':is(ol,ul)'));
assert.ok(listStyleLine);

for (const enabled of [true, false]) {
  test(`runtime replacement preserves RTL enabled=${enabled}`, () => {
    const preferences = { enabled };
    let oldObserverActive = true;
    const oldRuntime = {
      installed: true, stopped: !enabled,
      stop() { preferences.enabled = false; oldObserverActive = true; },
      disconnectApplyObserver() { oldObserverActive = false; },
    };
    const context = vm.createContext({ KEY: '__agentsRtl', RTL_ENABLED_STORAGE_KEY: 'rtlEnabled',
      window: { __agentsRtl: oldRuntime }, clearInterval() {},
      storedBoolean() { return preferences.enabled; },
      saveBoolean(key, value) { assert.equal(key, 'rtlEnabled'); preferences.enabled = value; },
    });
    vm.runInContext(readPart('72_10_legacy_listener_cleanup.js'), context);
    assert.equal(preferences.enabled, enabled);
    assert.equal(oldObserverActive, false, 'replaced runtime must not continue observing DOM changes');
  });
}

function measureFirstTextCharacter(textNode) {
  const start = textNode.textContent.search(/\S/u);
  if (start < 0) throw new Error('Expected visible text');
  const characterLength = String.fromCodePoint(textNode.textContent.codePointAt(start)).length;
  const range = document.createRange();
  range.setStart(textNode, start);
  range.setEnd(textNode, start + characterLength);
  const rect = range.getBoundingClientRect();
  return { left: rect.left, right: rect.right, top: rect.top };
}

function runListDirectionProbe() {
  const style = document.createElement('style');
  style.textContent = LIST_STYLES + '\nbody{margin:0;background:#1f1f1f;color:#eee;font:14px/22px Arial}' +
    'section{padding:24px;box-sizing:border-box}li{margin:3px 0}p{margin:4px 0}pre,code{direction:ltr;unicode-bidi:isolate}';
  document.head.appendChild(style);
  const reported = '<ul dir="auto"><li>🇰🇼 <strong>Country:</strong> Kuwait</li>' +
    '<li>🏠 <strong>Type:</strong> Residential</li><li>🔒 <strong>Sticky:</strong> نفس الـ IP خلال الجلسة.</li>' +
    '<li>⏱️ <strong>Session time:</strong> 60 ثانية.</li><li>🌐 <strong>Protocol:</strong> HTTP</li>' +
    '<li>✅ <strong>Generated:</strong> بروكسي واحد.</li></ul>';
  const fixtures = [
    ['reported', reported, ['rtl']],
    ['english', '<ul><li>Country: Kuwait</li><li>HTTP</li></ul>', ['ltr']],
    ['ordered', '<ol start="4"><li>Country: Kuwait</li><li>نفس الجلسة</li></ol>', ['rtl']],
    ['loose', '<ul><li><p>🇰🇼 <strong>Country:</strong> Kuwait</p></li><li><p>البلد الكويت</p></li></ul>', ['rtl']],
    ['nested', '<ul><li>الإعدادات<ul><li>Country: Kuwait</li><li>Type: Residential</li></ul></li>' +
      '<li>الاختبار<ol><li>HTTP</li><li>نتيجة الاختبار</li></ol></li></ul>', ['rtl', 'ltr', 'rtl']],
    ['nested-arabic', '<ul><li>Parent<ul><li>عنصر عربي</li></ul></li></ul>', ['rtl', 'rtl']],
    ['tasks', '<ul><li><input type="checkbox" disabled checked>Country: Kuwait</li>' +
      '<li><input type="checkbox" disabled>نفس الجلسة</li></ul>', ['rtl']],
    ['formatted-arabic', '<ul><li>📌 <strong dir="rtl" style="unicode-bidi:isolate">الخلاصة:</strong> الميليشيا أفضل للدفاع.</li></ul>', ['rtl']],
  ];
  const results = [];
  for (const width of [760, 375]) {
    for (const [name, html, expectedDirections] of fixtures) {
      const section = document.createElement('section');
      section.style.width = width + 'px';
      section.innerHTML = html + '<pre dir="ltr"><code>curl -x http://example.test:7000</code></pre>';
      document.body.appendChild(section);
      const originalText = section.textContent;
      const originalNodes = [...section.querySelectorAll('*')];
      const originalPresentation = originalNodes.map(element => ({ dir: element.getAttribute('dir'),
        textAlign: element.style.textAlign, unicodeBidi: element.style.unicodeBidi }));
      section.querySelectorAll(WEBVIEW_CHAT_TEXT_SELECTOR).forEach(applyTextDirection);
      const lists = [...section.querySelectorAll('ul,ol')];
      const items = [...section.querySelectorAll('li')];
      const result = { name, width, expectedDirections,
        directions: lists.map(element => getComputedStyle(element).direction),
        markerSides: items.every(element => getComputedStyle(element).direction === getComputedStyle(element.parentElement).direction),
        padding: lists.map(element => ({ start: getComputedStyle(element).paddingInlineStart, end: getComputedStyle(element).paddingInlineEnd })),
        nodesPreserved: originalNodes.every((element, index) => section.querySelectorAll('*')[index] === element),
        textPreserved: section.textContent === originalText,
        codeDirection: getComputedStyle(section.querySelector('pre')).direction,
        checkboxes: [...section.querySelectorAll('input')].map(element => ({ checked: element.checked, disabled: element.disabled })),
        paragraphs: [...section.querySelectorAll('p')].map(element => ({ direction: element.dir, alignment: element.style.textAlign })),
        overflow: section.scrollWidth > section.clientWidth,
      };
      if (name === 'reported') {
        result.englishPositions = [items[0].firstChild, items[0].querySelector('strong').firstChild, items[0].lastChild].map(measureFirstTextCharacter);
        result.arabicPositions = [items[2].firstChild, items[2].querySelector('strong').firstChild, items[2].lastChild].map(measureFirstTextCharacter);
      }
      if (name === 'formatted-arabic') {
        result.arabicPositions = [items[0].firstChild, items[0].querySelector('strong').firstChild, items[0].lastChild].map(measureFirstTextCharacter);
      }
      const mutations = new MutationObserver(() => {});
      mutations.observe(section, { attributes: true, childList: true, subtree: true, characterData: true });
      section.querySelectorAll(WEBVIEW_CHAT_TEXT_SELECTOR).forEach(applyTextDirection);
      result.repeatMutations = mutations.takeRecords().length;
      mutations.disconnect();
      section.querySelectorAll('[' + MANAGED_ATTRIBUTE_NAME + ']').forEach(restoreManagedElement);
      result.restored = originalNodes.every((element, index) => {
        const previous = originalPresentation[index];
        return element.getAttribute('dir') === previous.dir && element.style.textAlign === previous.textAlign &&
          element.style.unicodeBidi === previous.unicodeBidi && !element.hasAttribute(MANAGED_ATTRIBUTE_NAME);
      });
      results.push(result);
    }
  }
  // Antigravity's selector does not include UL/OL; applying a list item must
  // still establish its parent-list direction, including after streaming updates.
  const streaming = document.createElement('div');
  streaming.innerHTML = '<ul><li>Country: Kuwait</li></ul>';
  document.body.appendChild(streaming);
  streaming.querySelectorAll(ANTIGRAVITY_CHAT_TEXT_SELECTOR).forEach(applyTextDirection);
  const initialDirection = streaming.firstElementChild.dir;
  const addedItem = document.createElement('li');
  addedItem.textContent = 'عنصر عربي';
  streaming.firstElementChild.appendChild(addedItem);
  streaming.querySelectorAll(ANTIGRAVITY_CHAT_TEXT_SELECTOR).forEach(applyTextDirection);
  const streamingResult = { initialDirection, finalDirection: streaming.firstElementChild.dir,
    items: [...streaming.querySelectorAll('li')].map(element => element.dir) };
  const result = document.createElement('pre');
  result.id = 'test-result';
  result.hidden = true;
  result.textContent = JSON.stringify({ results, streamingResult });
  document.body.appendChild(result);
}

test('native DOM lists align markers and text, preserve bidi ordering and restore cleanly', () => {
  const directory = mkdtempSync(path.join(tmpdir(), 'agents-rtl-list-test-'));
  try {
    const pagePath = path.join(directory, 'probe.html');
    const scriptPath = path.join(directory, 'probe.js');
    writeFileSync(scriptPath, productionFunctions + '\nconst LIST_STYLES = [' + listStyleLine + '].join("\\n");\n' +
      measureFirstTextCharacter.toString() + '\n(' + runListDirectionProbe.toString() + ')();');
    writeFileSync(pagePath, '<meta charset="utf-8"><body><script src="' + pathToFileURL(scriptPath) + '"></script>');
    const output = execFileSync('/usr/bin/chromium', ['--headless', '--no-sandbox', '--disable-gpu',
      '--disable-background-networking', '--no-first-run', '--user-data-dir=' + path.join(directory, 'profile'),
      '--dump-dom', pathToFileURL(pagePath).href],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 30000 });
    const payload = output.match(/<pre id="test-result" hidden="">(.*?)<\/pre>/su);
    assert.ok(payload, output);
    const { results, streamingResult } = JSON.parse(payload[1].replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>'));
    assert.equal(results.length, 16);
    for (const result of results) {
      assert.deepEqual(result.directions, result.expectedDirections, result.name);
      assert.equal(result.markerSides, true, result.name);
      for (const [index, padding] of result.padding.entries()) {
        assert.equal(padding.end, '0px');
        assert.equal(padding.start, result.directions[index] === 'rtl' ? '24px' : '40px');
      }
      assert.equal(result.nodesPreserved, true, result.name);
      assert.equal(result.textPreserved, true, result.name);
      assert.equal(result.codeDirection, 'ltr');
      assert.equal(result.repeatMutations, 0, result.name);
      assert.equal(result.restored, true, result.name);
      assert.equal(result.overflow, false, result.name);
      if (result.englishPositions) {
        assert.ok(result.englishPositions[0].left < result.englishPositions[1].left);
        assert.ok(result.englishPositions[1].left < result.englishPositions[2].left);
      }
      if (result.arabicPositions) {
        assert.ok(result.arabicPositions[0].right > result.arabicPositions[1].right, JSON.stringify(result.arabicPositions));
        assert.ok(result.arabicPositions[1].right > result.arabicPositions[2].right, JSON.stringify(result.arabicPositions));
      }
      if (result.name === 'loose') assert.deepEqual(result.paragraphs, [
        { direction: 'ltr', alignment: 'right' }, { direction: 'rtl', alignment: 'right' },
      ]);
      if (result.name === 'tasks') assert.deepEqual(result.checkboxes, [
        { checked: true, disabled: true }, { checked: false, disabled: true },
      ]);
    }
    assert.deepEqual(streamingResult, { initialDirection: 'ltr', finalDirection: 'rtl', items: ['rtl', 'rtl'] });
  } finally {
    rmSync(directory, { recursive: true });
  }
});
