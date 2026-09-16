/* 发词工作台：核对识别结果，补全释义，确认后写入生词本。 */
(() => {
  'use strict';
  const {esc, api, toast, mountNav} = App;
  mountNav('workbench.html');

  const params = new URLSearchParams(location.search);
  const state = {result: null, selected: new Set(), mode: 'extract', words: [], tokenize: null};
  const sourceCategory = document.querySelector('#source-category');
  const sourceName = document.querySelector('#source-name');
  const sourceLink = document.querySelector('#source-link');
  const sourceLocation = document.querySelector('#source-location');

  const yearSelect = document.querySelector('#year');
  const sectionSelect = document.querySelector('#section');
  for (let year = 2025; year >= 2006; year -= 1) {
    const option = document.createElement('option');
    option.value = year;
    option.textContent = `${year} 英语（一）${year < 2010 ? '（旧卷）' : ''}`;
    yearSelect.append(option);
  }
  const custom = document.createElement('option');
  custom.value = 'custom';
  custom.textContent = '其他材料（练习册 / 手写）';
  yearSelect.prepend(custom);

  const MARK_LABELS = {circle: '圈画', underline: '划线', highlight: '荧光笔',
                       color: '彩色笔迹', listed: '文中出现'};

  // ------------------------------------------------------------ 载入
  function message(html, kind = '') {
    document.querySelector('#messages').insertAdjacentHTML('beforeend',
      `<div class="notice ${kind}">${html}</div>`);
  }

  async function boot() {
    if (['paste', 'pending', 'capture'].includes(params.get('mode'))) {
      document.querySelector('#paste-card').hidden = false;
    }
    if (params.get('mode') === 'pending') await loadPending();
    const id = params.get('id');
    if (params.get('mode') === 'paste') {
      const saved = sessionStorage.getItem('paste-payload');
      if (saved) {
        const {text, name, link, category, location: place} = JSON.parse(saved);
        document.querySelector('#paste-text').value = text;
        document.querySelector('#paste-name').value = name;
        if (link) sourceLink.value = link;
        if (category) sourceCategory.value = category;
        if (place) sourceLocation.value = place;
        sessionStorage.removeItem('paste-payload');
        await analyzePaste();
      }
      return;
    }
    if (!id) {
      if (params.get('mode') !== 'pending') {
        document.querySelector('#title').textContent = '发词工作台';
        document.querySelector('#subtitle').textContent =
          '请从首页上传试卷，或在上方粘贴文字后开始整理。';
        document.querySelector('#paste-card').hidden = false;
      }
      return;
    }
    try {
      const {result} = await api(`/api/extraction?id=${encodeURIComponent(id)}`);
      state.result = result;
      state.mode = 'extract';
      render();
    } catch (error) {
      message(`读取识别结果失败：${esc(error.message)}`, 'bad');
      document.querySelector('#paste-card').hidden = false;
    }
  }

  async function loadPending() {
    try {
      const data = await api('/api/status');
      const words = data.pending || [];
      if (!words.length) { message('待整理清单是空的。在“原文定位”里查词时可以加入待整理。'); return; }
      const resolved = await api('/api/resolve_pending', {
        method: 'POST', body: JSON.stringify({words: words.map(item => item.word)}),
      });
      state.result = {
        id: 'pending', source: '待整理清单', engine: 'pending', pages: [],
        resolution: {year: null, section: null}, stats: {candidates: words.length, known: 0},
        candidates: resolved.candidates.map(item => ({...item, sentence: item.example || ''})),
      };
      state.result.stats.known = state.result.candidates.filter(item => item.known).length;
      state.mode = 'pending';
      render();
    } catch (error) { message(`读取待整理清单失败：${esc(error.message)}`, 'bad'); }
  }

  document.querySelector('#paste-analyze').addEventListener('click', analyzePaste);
  async function analyzePaste() {
    const text = document.querySelector('#paste-text').value.trim();
    if (!text) { toast('请先粘贴文字', 'bad'); return; }
    const button = document.querySelector('#paste-analyze');
    button.disabled = true;
    button.textContent = '分析中…';
    try {
      const {result} = await api('/api/prepare_text', {method: 'POST', body: JSON.stringify({
        text,
        name: document.querySelector('#paste-name').value.trim() || '阅读材料',
        category: sourceCategory.value,
        link: sourceLink.value.trim(),
        location: sourceLocation.value.trim(),
      })});
      state.result = result;
      state.mode = 'paste';
      render();
    } catch (error) {
      toast(error.message, 'bad');
    } finally {
      button.disabled = false;
      button.textContent = '分析这段文字';
    }
  }

  // ------------------------------------------------------------ 渲染
  function render() {
    const result = state.result;
    if (!result) return;
    const isExtract = state.mode === 'extract';
    document.querySelector('#title').textContent = isExtract ? '识别结果核对' : '整理候选生词';
    document.querySelector('#subtitle').textContent = isExtract
      ? `${result.source} · 引擎：${result.engine} · 逐条确认后写入生词本`
      : `${result.source} · 勾选要收录的词，再补上文中含义`;
    document.querySelector('#summary-card').hidden = false;
    document.querySelector('#save-bar').hidden = false;
    document.querySelector('#candidate-area').hidden = false;
    document.querySelector('#stat-candidates').textContent = `候选 ${result.stats.candidates}`;
    document.querySelector('#stat-known').textContent = `已在生词本 ${result.stats.known}`;
    document.querySelector('#stat-new').textContent = `待收录 ${result.stats.candidates - result.stats.known}`;

    if (result.category) sourceCategory.value = result.category;
    if (result.link) sourceLink.value = result.link;
    if (result.location) sourceLocation.value = result.location;
    if (result.source && sourceCategory.value !== 'exam' && !sourceName.value) sourceName.value = result.source;
    const resolution = result.resolution || {};
    yearSelect.value = resolution.year ? String(resolution.year) : 'custom';
    sectionSelect.value = resolution.section || '';
    document.querySelector('#source-hint').textContent = sourceCategory.value === 'exam'
      ? '真题试卷：年份和题型会自动匹配本地题库，可用来找原句位置。'
      : '外刊／书籍：不需要年份，原句取自你摘录的文字；填了链接就能随时回原文。';
    document.querySelector('#year').parentElement.hidden = sourceCategory.value !== 'exam';
    document.querySelector('#section').parentElement.hidden = sourceCategory.value !== 'exam';
    document.querySelector('#resolution-note').textContent = resolution.year
      ? `已匹配到 ${resolution.year} 年真题语境。年份不对时可以改选，再手动修正词条内容。`
      : '没有匹配到真题年份：按“其他材料”收录，原句取自你的材料文字。';
    document.querySelector('#only-marked').parentElement.hidden = !isExtract;

    renderPreview(result);
    renderList();
  }

  function mediaURL(path) {
    if (!path) return '';
    const marker = 'data/uploads/';
    const index = path.indexOf(marker);
    return '/media/' + encodeURI(index >= 0 ? path.slice(index + marker.length) : path);
  }

  function renderPreview(result) {
    const host = document.querySelector('#preview');
    const page = (result.pages || [])[0];
    if (!page || (!page.image && !page.text)) { host.hidden = true; return; }
    host.hidden = false;
    if (page.image) {
      const marks = (result.candidates || []).filter(item => item.page === page.page && item.box);
      host.innerHTML = `<div class="preview-wrap" style="position:relative">
        <img src="${esc(mediaURL(page.image))}" alt="识别页面预览">
        ${marks.map(item => `<span class="overlay-box ${esc(item.kind)}"
          style="left:${(item.box.x0 * 100).toFixed(2)}%;top:${(item.box.y0 * 100).toFixed(2)}%;
                 width:${((item.box.x1 - item.box.x0) * 100).toFixed(2)}%;
                 height:${((item.box.y1 - item.box.y0) * 100).toFixed(2)}%"
          data-jump="${esc(item.text)}" title="${esc(item.text)} · ${MARK_LABELS[item.kind] || ''}"></span>`).join('')}</div>
        <div class="row tight" style="margin-top:8px">
          <label class="inline small">旋转预览
            <select id="rotate-view"><option value="0">0°</option><option value="90">90°</option>
            <option value="180">180°</option><option value="270">270°</option></select></label>
        </div>`;
      host.querySelectorAll('[data-jump]').forEach(box => {
        box.style.pointerEvents = 'auto';
        box.style.cursor = 'pointer';
        box.addEventListener('click', () => document.querySelector(`[data-word="${CSS.escape(box.dataset.jump)}"]`)
          ?.scrollIntoView({block: 'center', behavior: 'smooth'}));
      });
      const image = host.querySelector('img');
      host.querySelector('#rotate-view').addEventListener('change', event => {
        const degrees = Number(event.target.value);
        image.style.transform = `rotate(${degrees}deg)`;
        image.style.maxHeight = degrees % 180 ? '60vh' : 'none';
      });
    } else {
      host.innerHTML = renderTextLayer(page.text);
    }
  }

  function renderTextLayer(text) {
    const lines = String(text).split('\n').slice(0, 120);
    return `<div class="text-layer">${lines.map((line, index) =>
      `<div class="line" data-line="${index}">${line.split(/(\s+)/).map(piece =>
        /^[A-Za-z][A-Za-z'-]*$/.test(piece)
          ? `<span class="token" data-mark="${esc(piece)}" title="点击加入候选">${esc(piece)}</span>`
          : esc(piece)).join('')}</div>`).join('')}</div>`;
  }

  document.addEventListener('click', event => {
    const token = event.target.closest('[data-mark]');
    if (!token) return;
    event.preventDefault();
    addManual(token.dataset.mark, token);
  });

  async function addManual(word, anchor) {
    if (state.result.candidates.some(item => item.text.toLowerCase() === word.toLowerCase())) {
      toast(`${word} 已经在候选列表里`);
      return;
    }
    try {
      const data = await api(`/api/lookup?q=${encodeURIComponent(word)}`);
      const location = data.locations?.[0];
      state.result.candidates.push({
        text: word, kind: 'listed', score: 0, colored: false, evidence: {}, page: 0, crop: '',
        known: data.level === 'vocabulary', known_lemma: data.entry?.lemma || '',
        meaning: data.entry?.short_meaning || '', manual: true,
        sentence: location?.text || '', example: location?.text || '', context: location || null,
        dict: data.dictionary || null,
      });
      renderList();
      toast(`已加入候选：${word}`, 'ok');
    } catch (error) { toast(error.message, 'bad'); }
  }

  function candidateCard(item, index) {
    const dictionary = item.dict || {};
    const senses = (dictionary.senses || []).slice(0, 6);
    const example = item.example || item.sentence || '';
    const isMarked = ['circle', 'underline', 'highlight', 'color'].includes(item.kind);
    const card = document.createElement('article');
    card.className = `word-card${item.known ? ' known' : ''}`;
    card.dataset.word = item.text;
    const checked = !item.known && !item.auxiliary && !item.ambiguous && !item.manual;
    card.innerHTML = `
      ${item.crop ? `<img class="thumb" src="/media/${esc(`${state.result.id}/${item.crop}`)}" alt="${esc(item.text)} 的圈画位置">`
                  : `<div class="thumb" aria-hidden="true"></div>`}
      <div>
        <div class="word-line">
          <label class="inline"><input type="checkbox" data-pick ${item.known ? 'disabled' : ''}
            ${checked ? 'checked' : ''}></label>
          <span class="headword">${esc(item.text)}</span>
          <button class="speak" type="button" data-say="${esc(item.text)}">▶</button>
          ${isMarked ? `<span class="chip gold">${MARK_LABELS[item.kind]} · ${(item.score * 100).toFixed(0)}%</span>` : ''}
          ${item.auxiliary ? '<span class="chip">跟着笔迹扫到的功能词</span>' : ''}
          ${item.ambiguous ? '<span class="chip">笔迹跨多个词，请确认</span>' : ''}
          ${item.manual ? '<span class="chip accent">手动补选</span>' : ''}
          ${item.known ? `<span class="chip ok">已在生词本（${esc(item.known_lemma)}）</span>`
                       : (dictionary.word ? '<span class="chip">本地词典有释义</span>' : '')}
          <button class="tiny ghost" type="button" data-lookup="${esc(item.text)}">查原文位置</button>
        </div>
        ${example ? `<p class="sentence en">${App.highlight(example, [item.text, item.known_lemma].filter(Boolean))}
          <button class="speak" type="button" data-say="${esc(example)}">▶ 原句</button></p>` : ''}
        ${item.context ? `<div class="meta">
            <span>${esc(item.context.section_title || '')} · ${esc(item.context.location || '')}</span>
            ${item.context.score ? `<span>匹配度 ${(item.context.score * 100).toFixed(0)}%</span>` : ''}
            <a href="../output/exams/${esc(item.context.year)}.html#${esc(item.context.anchor || '')}">整卷核对</a></div>`
          : '<div class="meta"><span>未匹配到真题原句，将按材料原文收录</span></div>'}
        <div class="candidate-fields">
          <label>词形（原形）<input type="text" data-f="lemma" value="${esc(item.known_lemma || dictionary.word || item.text.toLowerCase())}"></label>
          <label>文中形式<input type="text" data-f="form" value="${esc(item.text)}"></label>
          <label>词形变化（空格分隔）<input type="text" data-f="forms"
            value="${esc([item.text, ...(dictionary.forms || [])].filter(Boolean).join(' '))}"></label>
          <label>音标<input type="text" data-f="ipa" value="${esc(dictionary.phonetic || '')}"></label>
          <label>词性<input type="text" data-f="pos" value="${esc((dictionary.pos || '').split('/')[0] || '')}"></label>
          <label>文中含义（必填）<input type="text" data-f="meaning" value="${esc(item.meaning || '')}" placeholder="如：adj. 严酷的（形容劳动力市场）"></label>
          <label>常见词义<input type="text" data-f="common" value="${esc(senses.slice(0, 3).map(s => `${s.pos} ${s.meaning}`).join('；'))}"></label>
          <label>中文翻译<input type="text" data-f="translation" value="${esc(item.translation || '')}" placeholder="原句的中文"></label>
        </div>
        ${senses.length ? `<div class="sense-picker">${senses.map(s =>
          `<button type="button" data-sense="${esc(`${s.pos} ${s.meaning}`)}">${esc(s.pos)} ${esc(s.meaning)}</button>`).join('')}</div>` : ''}
        <div class="actions">
          <button class="tiny" type="button" data-skip>${item.known ? '已在生词本，跳过' : '不收录这个词'}</button>
          <span class="evidence">${item.evidence?.pixels ? `笔迹 ${item.evidence.pixels}px · 长笔画 ${item.evidence.stroke_p95}px · 彩色 ${item.evidence.colored_pixels}px` : ''}</span>
        </div>
      </div>`;
    const pick = card.querySelector('[data-pick]');
    pick?.addEventListener('change', () => {
      if (pick.checked) state.selected.add(index); else state.selected.delete(index);
      updateCount();
    });
    card.querySelectorAll('[data-sense]').forEach(button => {
      button.addEventListener('click', () => {
        const target = card.querySelector('[data-f="common"]');
        target.value = target.value ? `${target.value}；${button.dataset.sense}` : button.dataset.sense;
        const meaning = card.querySelector('[data-f="meaning"]');
        if (!meaning.value) meaning.value = button.dataset.sense;
      });
    });
    card.querySelector('[data-skip]').addEventListener('click', () => {
      if (pick) pick.checked = false;
      state.selected.delete(index);
      card.classList.add('skipped');
      updateCount();
    });
    return card;
  }

  function renderList() {
    const host = document.querySelector('#candidates');
    const onlyMarked = document.querySelector('#only-marked').checked;
    const hideKnown = document.querySelector('#hide-known').checked;
    const result = state.result;
    state.selected.clear();
    host.replaceChildren();
    let shown = 0;
    (result.candidates || []).forEach((item, index) => {
      const isMarked = ['circle', 'underline', 'highlight', 'color'].includes(item.kind);
      if (onlyMarked && state.mode === 'extract' && !isMarked) return;
      if (hideKnown && item.known) return;
      const card = candidateCard(item, index);
      const box = card.querySelector('[data-pick]');
      if (box?.checked) state.selected.add(index);
      host.append(card);
      shown += 1;
    });
    if (!shown) {
      host.innerHTML = `<div class="empty">没有符合当前筛选条件的词。
        ${state.mode === 'extract' ? '这个文件可能没有被圈画的词；可以关掉筛选，或在下面的原文里点词手动补选。' : ''}</div>`;
    }
    document.querySelector('#list-title').textContent = `候选生词（显示 ${shown} 个）`;
    updateCount();
  }

  function updateCount() {
    document.querySelector('#selected-count').textContent = `已选 ${state.selected.size} 个`;
  }

  sourceCategory.addEventListener('change', () => {
    document.querySelector('#year').parentElement.hidden = sourceCategory.value !== 'exam';
    document.querySelector('#section').parentElement.hidden = sourceCategory.value !== 'exam';
    document.querySelector('#source-hint').textContent = sourceCategory.value === 'exam'
      ? '真题试卷：年份和题型会自动匹配本地题库，可用来找原句位置。'
      : '外刊／书籍：不需要年份，原句取自你摘录的文字；填了链接就能随时回原文。';
  });
  document.querySelector('#reanalyze').addEventListener('click', () => {
    const text = document.querySelector('#paste-text').value.trim();
    if (!text) { toast('请先在上方粘贴或修改文字', 'bad'); return; }
    analyzePaste();
  });

  document.addEventListener('input', event => {
    if (event.target.matches('[data-f="meaning"], [data-f="common"]')) {
      event.target.classList.remove('needs-input');
    }
  });

  document.querySelector('#only-marked').addEventListener('change', renderList);
  document.querySelector('#hide-known').addEventListener('change', renderList);
  document.querySelector('#select-none').addEventListener('click', () => {
    document.querySelectorAll('#candidates [data-pick]').forEach(box => { box.checked = false; });
    state.selected.clear();
    updateCount();
  });
  document.querySelector('#select-all').addEventListener('click', () => {
    document.querySelectorAll('#candidates .word-card').forEach(card => {
      const box = card.querySelector('[data-pick]');
      if (box && !box.disabled) box.checked = true;
    });
    syncSelected();
  });
  document.querySelector('#select-recommended').addEventListener('click', () => {
    document.querySelectorAll('#candidates .word-card').forEach(card => {
      const box = card.querySelector('[data-pick]');
      const item = state.result.candidates.find(entry => entry.text === card.dataset.word);
      if (!box || box.disabled) return;
      box.checked = !item?.auxiliary && !item?.ambiguous;
    });
    syncSelected();
  });

  function syncSelected() {
    state.selected.clear();
    document.querySelectorAll('#candidates .word-card').forEach(card => {
      const box = card.querySelector('[data-pick]');
      if (box?.checked) {
        const index = state.result.candidates.findIndex(entry => entry.text === card.dataset.word);
        if (index >= 0) state.selected.add(index);
      }
    });
    updateCount();
  }

  // ------------------------------------------------------------ 保存
  const FIELD_KEYS = ['lemma', 'form', 'forms', 'ipa', 'pos', 'meaning', 'common', 'translation'];

  function collect() {
    const result = state.result;
    const year = yearSelect.value && yearSelect.value !== 'custom' ? Number(yearSelect.value) : null;
    const section = sectionSelect.value || null;
    const entries = [];
    document.querySelectorAll('#candidates .word-card').forEach(card => {
      const box = card.querySelector('[data-pick]');
      if (!box || !box.checked || box.disabled) return;
      const item = result.candidates.find(entry => entry.text === card.dataset.word);
      if (!item) return;
      const values = {};
      FIELD_KEYS.forEach(key => { values[key] = card.querySelector(`[data-f="${key}"]`)?.value.trim() || ''; });
      const forms = values.forms.split(/\s+/).filter(Boolean);
      const example = item.example || item.sentence || '';
      if (!example) { toast(`${item.text} 没有原句，已跳过`, 'bad'); return; }
      const category = sourceCategory.value;
      const name = sourceName.value.trim() || (result.source !== '待整理清单' ? result.source : '') || '阅读材料';
      const isExam = category === 'exam' && year;
      entries.push({
        lemma: values.lemma || item.text.toLowerCase(),
        form: values.form || item.text,
        forms: forms.length ? forms : [item.text],
        ipa: values.ipa, pos: values.pos,
        meaning: values.meaning, common: values.common,
        short_meaning: values.meaning || values.common,
        translation: values.translation,
        example,
        year: isExam ? year : null,
        category,
        source_name: name,
        link: sourceLink.value.trim(),
        captured_at: new Date().toISOString().slice(0, 10),
        capture: state.mode === 'extract' ? 'photo' : 'text',
        section_id: isExam ? `${year}-${section || 'exam'}` : `read-${result.id}`,
        section_title: item.context?.section_title || (isExam
          ? `${year} 英语（一）` : `${name}${sourceLocation.value.trim() ? '｜' + sourceLocation.value.trim() : ''}`),
        location: item.context?.location || sourceLocation.value.trim()
          || (item.page ? `材料第 ${item.page} 页` : '摘录段落'),
        material_id: result.id, material_name: name,
        exam_record_id: item.context?.record_id || '',
        page: item.page || 0, mark_kind: item.kind, crop: item.crop || '',
        source_image: /\.(jpe?g|png|heic|pdf)$/i.test(result.source || '') ? result.source : '',
      });
    });
    return entries;
  }

  /** 个人词库按“词义”去重，所以每条必须有释义；缺释义的当场指出，不写半成品。 */
  function missingMeaning() {
    const missing = [];
    document.querySelectorAll('#candidates .word-card').forEach(card => {
      const box = card.querySelector('[data-pick]');
      if (!box || !box.checked || box.disabled) return;
      const meaning = card.querySelector('[data-f="meaning"]');
      const common = card.querySelector('[data-f="common"]');
      if (!(meaning?.value.trim() || common?.value.trim())) {
        missing.push(card);
        meaning?.classList.add('needs-input');
      }
    });
    return missing;
  }

  document.querySelector('#save').addEventListener('click', async event => {
    const missing = missingMeaning();
    if (missing.length) {
      toast(`还有 ${missing.length} 个词没有填“文中含义”或“常见词义”，个人词库按词义去重，必须填写`, 'bad');
      missing[0].scrollIntoView({block: 'center', behavior: 'smooth'});
      missing[0].querySelector('[data-f="meaning"]')?.focus();
      return;
    }
    const entries = collect();
    if (!entries.length) { toast('没有勾选任何可收录的词', 'bad'); return; }
    event.target.disabled = true;
    event.target.textContent = '保存中…';
    try {
      const data = await api('/api/save', {method: 'POST', body: JSON.stringify({entries})});
      const parts = [`新增 ${data.created.length} 条`];
      if (data.skipped.length) parts.push(`已在库中 ${data.skipped.length} 条`);
      if (data.errors.length) parts.push(`失败 ${data.errors.length} 条`);
      toast(parts.join('，'), data.errors.length ? 'bad' : 'ok');
      const cardNote = data.cards?.length
        ? `同时生成 ${data.cards.length} 张个人词库卡片，重新生成页面后会并入“查词与收词”的个人词库。` : '';
      message(`保存完成：${esc(parts.join('，'))}。生词本现有 ${data.total} 条记录。${esc(cardNote)}
        点“生成复习页面”后即可在生词本、背词练习和个人词库里看到。`, data.errors.length ? 'warn' : '');
      if (data.errors.length) message(esc(data.errors.join('；')), 'bad');
    } catch (error) {
      toast(error.message, 'bad');
    } finally {
      event.target.disabled = false;
      event.target.textContent = '保存所选词到生词本';
    }
  });

  document.querySelector('#rebuild').addEventListener('click', async event => {
    event.target.disabled = true;
    event.target.textContent = '生成中…';
    try {
      await api('/api/rebuild', {method: 'POST', body: '{}'});
      toast('复习页面已重新生成', 'ok');
      message('复习页面已重新生成：<a href="../output/index.html">简短总复习</a> · '
        + '<a href="vocabulary.html">生词本</a> · <a href="practice.html">背词练习</a>');
    } catch (error) {
      toast(`生成失败：${error.message}`, 'bad');
    } finally {
      event.target.disabled = false;
      event.target.textContent = '生成复习页面';
    }
  });

  boot();
})();
