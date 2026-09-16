/* 原文定位：两级查词。已录入生词本 → 完整资料；未录入 → 只给原文位置。 */
(() => {
  'use strict';
  const {esc, api, toast, mountNav, highlight} = App;
  mountNav('reader.html');

  const form = document.querySelector('#form');
  const wordInput = document.querySelector('#word');
  const yearSelect = document.querySelector('#year');
  const sectionSelect = document.querySelector('#section');
  const result = document.querySelector('#result');

  for (let year = 2025; year >= 2006; year -= 1) {
    const option = document.createElement('option');
    option.value = year;
    option.textContent = `${year} 英语（一）${year < 2010 ? '（旧卷）' : ''}`;
    yearSelect.append(option);
  }

  const KIND_LABELS = {passage: '正文', paragraph_option: '待选段落', question: '题干',
                       option: '选项（不代表正确答案）', directions: '作答说明', writing: '写作题目'};

  function locationCard(location) {
    return `<article class="card" style="margin-top:10px">
      <div class="row tight">
        <span class="chip accent">${esc(location.year)} · ${esc(location.section_name)}</span>
        <span class="chip">${esc(KIND_LABELS[location.kind] || location.kind)}</span>
        <span class="small muted">${esc(location.location)}</span>
        <span class="spacer"></span>
        <a class="tiny" href="${esc(location.paper)}#${esc(location.anchor)}" target="_blank" rel="noopener">整卷核对</a>
      </div>
      <p class="en" style="margin:10px 0 0;font-size:16.5px;line-height:1.75">${highlight(location.text, location.matched || [])}</p>
    </article>`;
  }

  function render(data) {
    const parts = [];
    const word = data.word;
    if (data.level === 'vocabulary') {
      const entry = data.entry;
      const dict = data.dictionary || {};
      parts.push(`<div class="card">
        <div class="row tight">
          <span class="chip ok">已在生词本</span>
          <span class="chip">原形 ${esc(entry.lemma)}</span>
          ${entry.ipa ? `<span class="small muted">${esc(entry.ipa)}</span>` : ''}
          <button class="speak tiny" type="button" data-say="${esc(entry.speech_word || entry.lemma)}">▶ 单词</button>
          <a class="button tiny" href="practice.html?unit=${encodeURIComponent(entry.id)}">练习此词</a>
        </div>
        <h2 class="en" style="margin:14px 0 6px;font-size:24px">${esc(entry.display || entry.lemma)}</h2>
        <p style="margin:0 0 6px">${esc(entry.short_meaning || entry.meaning || '')}</p>
        ${entry.common ? `<p class="small muted">常见词义：${esc(entry.common)}</p>` : ''}
        ${entry.example ? `<p class="sentence en">${highlight(entry.example, entry.forms || [entry.lemma])}
          <button class="speak" type="button" data-say="${esc(entry.example)}">▶ 原句</button></p>` : ''}
        ${entry.translation ? `<p class="small muted">${esc(entry.translation)}</p>` : ''}
        <div class="meta small muted">${esc(entry.section_title || '')} · ${esc(entry.location || '')}
          ${entry.link ? ` · <a href="${esc(entry.link)}" target="_blank" rel="noopener">回原文</a>` : ''}</div>
      </div>`);
      if (dict.senses?.length) {
        parts.push(`<div class="card"><h3>离线词典释义</h3>
          ${dict.senses.map(sense => `<div class="sense"><b>${esc(sense.pos)}</b> ${esc(sense.meaning)}</div>`).join('')}
          <p class="small muted" style="margin:10px 0 0">词典释义只作参考，以生词本里记录的文中含义为准。</p></div>`);
      }
    } else {
      parts.push(`<div class="card">
        <div class="row tight">
          <span class="chip gold">未录入生词本</span>
          <span class="chip">只显示原文位置</span>
        </div>
        <h2 class="en" style="margin:14px 0 6px;font-size:24px">${esc(word)}</h2>
        <p class="small muted">按规则，这个词没有收录进你的生词本，所以不显示释义。
          如果它确实是你想背的词，可以在下方结果里把它加入待整理清单，回到工作台补全原句和释义。</p>
        <button class="tiny" type="button" id="add-pending">加入待整理清单</button>
      </div>`);
    }

    parts.push(`<div class="row" style="margin:18px 0 4px">
      <h2>原文位置 <span class="small muted">${data.locations?.length || 0} 处</span></h2>
      <span class="spacer"></span>
      <a class="button tiny" href="workbench.html?mode=pending">打开待整理清单</a>
    </div>`);
    if (data.locations?.length) parts.push(data.locations.map(locationCard).join(''));
    else parts.push('<div class="empty">本地真题库里没有找到这个词形。请核对拼写，或换一个原文形式再查。</div>');
    result.innerHTML = parts.join('');

    const pendingButton = result.querySelector('#add-pending');
    if (pendingButton) {
      pendingButton.onclick = async () => {
        pendingButton.disabled = true;
        try {
          const added = await api('/api/pending', {method: 'POST', body: JSON.stringify({
            word, locations: data.locations?.slice(0, 6) || [], source: '原文定位',
          })});
          toast(added.added ? `已加入待整理：${word}` : `${word} 已在待整理清单里`, 'ok');
        } catch (error) { toast(error.message, 'bad'); pendingButton.disabled = false; }
      };
    }
  }

  async function lookup(word) {
    if (!word) return;
    result.innerHTML = '<div class="empty">正在查询…</div>';
    try {
      const params = new URLSearchParams({q: word});
      if (yearSelect.value) params.set('year', yearSelect.value);
      if (sectionSelect.value) params.set('section', sectionSelect.value);
      const data = await api(`/api/lookup?${params}`);
      render(data);
    } catch (error) {
      result.innerHTML = `<div class="empty">查询失败：${esc(error.message)}</div>`;
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    lookup(wordInput.value.trim());
  });
  yearSelect.addEventListener('change', () => { if (wordInput.value.trim()) lookup(wordInput.value.trim()); });
  sectionSelect.addEventListener('change', () => { if (wordInput.value.trim()) lookup(wordInput.value.trim()); });

  // 点结果里的英文词继续查
  result.addEventListener('click', event => {
    const token = event.target.closest('mark');
    if (!token) return;
    const text = token.textContent.replace(/[^A-Za-z'-]/g, '');
    if (text.length >= 2) { wordInput.value = text; lookup(text); }
  });

  const requested = new URLSearchParams(location.search).get('q');
  if (requested) { wordInput.value = requested; lookup(requested); }
})();
