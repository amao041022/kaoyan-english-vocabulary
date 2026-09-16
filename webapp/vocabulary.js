/* 生词本总览：按材料分组、搜索过滤、掌握程度与自测遮盖。 */
(() => {
  'use strict';
  const {esc, api, toast, mountNav} = App;
  mountNav('vocabulary.html');

  const list = document.querySelector('#list');
  const query = document.querySelector('#query');
  const groupSelect = document.querySelector('#group');
  const masterySelect = document.querySelector('#mastery');
  const categorySelect = document.querySelector('#category');
  const hideMeaning = document.querySelector('#hide-meaning');
  let entries = [];
  let ready = false;

  const unitOf = id => (window.VOCAB_STUDY?.entryUnits || {})[id] || '';
  const masteryTag = id => {
    const unitId = unitOf(id);
    if (!unitId) return '<span class="chip" data-state="new">未生成学习单元</span>';
    return `<button type="button" class="mastery chip" data-unit-id="${esc(unitId)}"
      data-state="new"><span>未学</span></button>`;
  };

  function render() {
    const term = query.value.trim().toLowerCase();
    const group = groupSelect.value;
    const mastery = masterySelect.value;
    const category = categorySelect.value;
    const states = window.StudyUI?.states || {};
    const fresh = window.StudyCore?.fresh ? StudyCore.fresh() : {status: 'new'};
    let shown = 0;
    list.replaceChildren();
    const sections = new Map();
    for (const entry of entries) {
      const status = states[unitOf(entry.id)]?.status || fresh.status;
      if (term && !`${entry.lemma} ${entry.form} ${entry.common} ${entry.meaning} ${entry.short_meaning} ${entry.section_title} ${entry.example}`.toLowerCase().includes(term)) continue;
      if (group && entry.source_group !== group) continue;
      if (category && (entry.category || 'exam') !== category) continue;
      if (mastery && status !== mastery) continue;
      const title = entry.section_title || entry.source_group || '未分组';
      if (!sections.has(title)) sections.set(title, []);
      sections.get(title).push({entry, status});
      shown += 1;
    }
    for (const [title, items] of sections) {
      const heading = document.createElement('h2');
      heading.style.margin = '22px 0 10px';
      heading.innerHTML = `${esc(title)} <span class="small muted">· ${items.length} 条</span>`;
      list.append(heading);
      for (const {entry} of items) list.append(card(entry));
    }
    if (!shown) list.innerHTML = '<div class="empty">没有匹配的词条。</div>';
    document.querySelector('#count').textContent = `显示 ${shown} / ${entries.length} 条`;
    list.classList.toggle('hide-meanings', hideMeaning.checked);
  }

  function card(entry) {
    const node = document.createElement('article');
    node.className = 'word-card';
    node.dataset.id = entry.id;
    const photos = entry.source_photos || (entry.photo ? [entry.photo] : []);
    node.innerHTML = `
      ${entry.crop ? `<img class="thumb" src="/media/${esc(entry.crop)}" alt="${esc(entry.lemma)} 的原文位置">`
                   : `<div class="thumb" aria-hidden="true" style="display:grid;place-items:center;font:600 13px var(--font-body);color:var(--ink-muted)">${esc((entry.source_group || '').slice(0, 6))}</div>`}
      <div>
        <div class="word-line">
          <span class="headword">${esc(entry.display || entry.lemma)}</span>
          ${masteryTag(entry.id)}
          <button class="speak" type="button" data-say="${esc(entry.speech_word || entry.display || entry.lemma)}">▶</button>
          ${entry.ipa ? `<span class="ipa muted small">${esc(entry.ipa)}</span>` : ''}
          <button class="tiny ghost" type="button" data-lookup="${esc(entry.lemma)}">查原文位置</button>
        </div>
        <p class="meaning" style="margin:6px 0 0">${esc(entry.short_meaning || entry.meaning || '')}</p>
        <p class="sentence en">${App.highlight(entry.example, entry.forms || [entry.lemma])}
          <button class="speak" type="button" data-say="${esc(entry.example)}">▶ 原句</button></p>
        ${entry.translation ? `<p class="translation">${esc(entry.translation)}</p>` : ''}
        <div class="meta">
          <span>${esc(entry.location || '')}</span>
          <span>原文词形：${esc(entry.form || entry.lemma)}</span>
          ${entry.link ? `<a href="${esc(entry.link)}" target="_blank" rel="noopener">回原文</a>` : ''}
          ${entry.common ? `<span>常见词义：${esc(entry.common)}</span>` : ''}
          ${photos.length ? photos.slice(0, 3).map((photo, index) =>
            `<a href="${esc(photo.startsWith('data/') || photo.startsWith('..') ? '../' + photo : '../images/' + encodeURIComponent(photo))}"
                target="_blank" rel="noopener">原图${photos.length > 1 ? index + 1 : ''}</a>`).join('') : ''}
        </div>
        ${entry.note ? `<p class="small muted" style="margin:6px 0 0">${esc(entry.note)}</p>` : ''}
      </div>`;
    return node;
  }

  [query, groupSelect, masterySelect, categorySelect].forEach(control =>
    control.addEventListener('input', render));
  hideMeaning.addEventListener('change', () => {
    list.classList.toggle('hide-meanings', hideMeaning.checked);
    document.querySelectorAll('.revealed').forEach(node => node.classList.remove('revealed'));
  });
  list.addEventListener('click', event => {
    const meaning = event.target.closest('.meaning');
    if (meaning && hideMeaning.checked) {
      meaning.classList.toggle('revealed');
      meaning.closest('.word-card').classList.toggle('revealed', meaning.classList.contains('revealed'));
    }
  });

  api('/api/vocabulary').then(data => {
    entries = data.entries || [];
    const groups = [...new Set(entries.map(entry => entry.source_group).filter(Boolean))];
    groupSelect.innerHTML = '<option value="">全部材料</option>' +
      groups.map(group => `<option value="${esc(group)}">${esc(group)}</option>`).join('');
    const requested = new URLSearchParams(location.search).get('q');
    if (requested) query.value = requested;
    render();
    ready = true;
  }).catch(error => {
    list.innerHTML = `<div class="empty">读取生词本失败：${esc(error.message)}<br>
      请确认本机服务正在运行（python3 vocabulary_app/server.py）。</div>`;
  });

  window.addEventListener('progresschange', () => { if (ready) render(); });
})();
