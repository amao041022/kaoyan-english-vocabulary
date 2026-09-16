/* 公共工具：接口调用、导航、提示、朗读、查词卡片。所有页面共用。 */
(() => {
  'use strict';

  const esc = value => String(value ?? '').replace(/[&<>"']/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: options.body instanceof FormData ? undefined : {'Content-Type': 'application/json'},
      ...options,
    });
    let payload;
    try { payload = await response.json(); } catch { throw new Error(`服务没有返回数据（HTTP ${response.status}）`); }
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `请求失败（HTTP ${response.status}）`);
    return payload;
  }

  // ------------------------------------------------------------ 提示
  function toast(message, kind = '') {
    let host = document.querySelector('#toast');
    if (!host) { host = document.createElement('div'); host.id = 'toast'; document.body.append(host); }
    const item = document.createElement('div');
    item.className = kind;
    item.textContent = message;
    host.append(item);
    setTimeout(() => item.remove(), kind === 'bad' ? 6000 : 3200);
  }

  // ------------------------------------------------------------ 导航
  const NAV = [
    ['app.html', '首页', '＋'],
    ['workbench.html', '上传整理', '✎'],
    ['vocabulary.html', '生词本', '☰'],
    ['reader.html', '原文定位', '⌕'],
    ['practice.html', '背词练习', '◎'],
  ];

  function mountNav(active) {
    const top = document.querySelector('.topbar');
    if (top) {
      top.innerHTML = `<a class="brand" href="app.html"><span class="brand-mark">词</span>
        <span><b>考研英语生词本</b><small>离线 · 语境记忆</small></span></a>
        <nav class="tabs">${NAV.map(([href, label]) =>
          `<a href="${href}"${href === active ? ' aria-current="page"' : ''}>${label}</a>`).join('')}</nav>`;
    }
    const bar = document.querySelector('.tabbar');
    if (bar) {
      bar.innerHTML = NAV.map(([href, label, icon]) =>
        `<a href="${href}"${href === active ? ' aria-current="page"' : ''}>
           <span class="ico" aria-hidden="true">${icon}</span>${label}</a>`).join('');
    }
  }

  // ------------------------------------------------------------ 朗读
  let currentAudio = null;
  async function speak(text, button) {
    if (!text) return;
    try {
      if (currentAudio) { currentAudio.pause(); currentAudio = null; }
      document.querySelectorAll('.speak.playing').forEach(el => el.classList.remove('playing'));
      const {url} = await api('/api/audio', {method: 'POST', body: JSON.stringify({text})});
      if (!url) { toast('本机没有可用的朗读音频，请先运行一次页面生成以补全', 'bad'); return; }
      const audio = new Audio(url);
      currentAudio = audio;
      button?.classList.add('playing');
      audio.addEventListener('ended', () => button?.classList.remove('playing'));
      await audio.play();
    } catch (error) {
      button?.classList.remove('playing');
      toast(error.message, 'bad');
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('.speak');
    if (button) { event.preventDefault(); speak(button.dataset.say || button.dataset.text, button); }
  });

  // ------------------------------------------------------------ 查词卡片
  let card = null;

  function closeLookup() { card?.remove(); card = null; }

  function placeLookup(anchor) {
    if (!card || !anchor) return;
    const rect = anchor.getBoundingClientRect();
    const width = card.offsetWidth;
    const height = card.offsetHeight;
    let left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
    let top = rect.bottom + 8;
    if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 8);
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
  }

  function highlight(text, forms) {
    const list = [...new Set(forms.filter(Boolean))].sort((a, b) => b.length - a.length);
    if (!list.length) return esc(text);
    const pattern = new RegExp('(?<![A-Za-z])(?:' +
      list.map(value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')(?![A-Za-z])', 'gi');
    let out = '', last = 0;
    for (const match of String(text).matchAll(pattern)) {
      out += esc(text.slice(last, match.index)) + '<mark>' + esc(match[0]) + '</mark>';
      last = match.index + match[0].length;
    }
    return out + esc(text.slice(last));
  }

  function locationHTML(location, index) {
    const kinds = {passage: '正文', paragraph_option: '待选段落', question: '题干',
                   option: '选项（不代表正确答案）', directions: '作答说明', writing: '写作题目'};
    return `<div class="loc">
      <div class="small"><b>${esc(location.year)} · ${esc(location.section_name)}</b>
        · ${esc(location.location)} · ${kinds[location.kind] || esc(location.kind)}
        <a class="small" href="${esc(location.paper)}#${esc(location.anchor)}">在整卷中核对</a></div>
      <p class="en">${highlight(location.text, location.matched || [])}</p>
    </div>`;
  }

  async function showLookup(word, anchor, options = {}) {
    closeLookup();
    card = document.createElement('div');
    card.className = 'lookup';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', `${word} 的查询结果`);
    card.innerHTML = `<button class="close ghost tiny" type="button" aria-label="关闭">×</button>
      <h3 class="en">${esc(word)}</h3><p class="muted small">正在查询…</p>`;
    document.body.append(card);
    placeLookup(anchor);
    card.querySelector('.close').onclick = closeLookup;

    const params = new URLSearchParams({q: word});
    if (options.year) params.set('year', options.year);
    if (options.section) params.set('section', options.section);

    let data;
    try {
      data = await api(`/api/lookup?${params}`);
    } catch (error) {
      card.querySelector('.muted').textContent = error.message;
      return;
    }
    const parts = [];
    if (data.level === 'vocabulary') {
      const entry = data.entry;
      const gloss = entry.short_meaning || entry.meaning || entry.common || '';
      parts.push(`<div class="row tight"><span class="chip ok">已在生词本</span>
        <span class="ipa muted small">${esc(entry.ipa || '')}</span></div>`);
      if (gloss) parts.push(`<p class="gloss">${esc(gloss)}</p>`);
      if (entry.meaning && entry.meaning !== gloss) parts.push(`<p class="small">文中含义：${esc(entry.meaning)}</p>`);
      if (entry.common) parts.push(`<p class="small muted">常见词义：${esc(entry.common)}</p>`);
      if (entry.example) {
        parts.push(`<p class="en small">${highlight(entry.example, entry.forms || [entry.lemma])}
          <button class="speak tiny" type="button" data-say="${esc(entry.example)}">▶ 例句</button></p>`);
      }
      if (entry.translation) parts.push(`<p class="small muted">${esc(entry.translation)}</p>`);
      if (entry.link) {
        parts.push(`<p class="small"><a href="${esc(entry.link)}" target="_blank" rel="noopener">查看原文（${esc(entry.source_name || new URL(entry.link).hostname)}）</a></p>`);
      }
      parts.push(`<div class="row tight" style="margin-top:10px">
        <button class="speak" type="button" data-say="${esc(entry.speech_word || entry.lemma)}">▶ 单词</button>
        <a class="button tiny" href="practice.html?unit=${encodeURIComponent(entry.id)}">练习此词</a>
        <a class="button tiny" href="vocabulary.html?q=${encodeURIComponent(entry.lemma)}">在生词本中查看</a></div>`);
    } else {
      parts.push(`<div class="row tight"><span class="chip gold">未录入生词本</span>
        <span class="chip">只显示原文位置</span></div>
        <p class="small muted">这个词不在你的生词本里，按规则不显示释义；可以据此定位原文，或加入待整理清单。</p>`);
    }
    parts.push(`<h4 class="small muted" style="margin:14px 0 4px">原文位置</h4>`);
    if (data.locations?.length) {
      parts.push(data.locations.slice(0, options.limit || 12).map(locationHTML).join(''));
      if (data.locations.length > (options.limit || 12)) {
        parts.push(`<p class="small muted">还有 ${data.locations.length - (options.limit || 12)} 处，请在“原文定位”页查看完整结果。</p>`);
      }
    } else {
      parts.push(`<p class="small muted">本地真题库里没有找到这个词形。</p>`);
    }
    parts.push(`<div class="row tight" style="margin-top:12px">
      <button class="tiny" type="button" id="lookup-add">加入待整理</button>
      <a class="tiny button" href="reader.html?q=${encodeURIComponent(word)}">打开原文定位</a></div>`);
    card.innerHTML = `<button class="close ghost tiny" type="button" aria-label="关闭">×</button>
      <h3 class="en">${esc(word)}</h3>${parts.join('')}`;
    card.querySelector('.close').onclick = closeLookup;
    card.querySelector('#lookup-add').onclick = async event => {
      event.target.disabled = true;
      try {
        await api('/api/pending', {method: 'POST', body: JSON.stringify({word, locations: data.locations?.slice(0, 6) || []})});
        toast(`已把 ${word} 加入待整理清单`, 'ok');
      } catch (error) { toast(error.message, 'bad'); } finally { event.target.disabled = false; }
    };
    placeLookup(anchor);
  }

  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-lookup]');
    if (trigger) { event.preventDefault(); showLookup(trigger.dataset.lookup, trigger); return; }
    if (card && !card.contains(event.target)) closeLookup();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeLookup(); });
  window.addEventListener('resize', () => closeLookup());

  // ------------------------------------------------------------ 其它
  async function status() { return api('/api/status'); }

  window.App = {esc, api, toast, mountNav, speak, showLookup, closeLookup, status, highlight,
                NAV, fmtDate: at => at ? new Date(at).toLocaleDateString('zh-CN') : ''};
})();
