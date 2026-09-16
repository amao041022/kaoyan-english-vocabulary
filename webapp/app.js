/* 首页：上传试卷、粘贴文字、查看最近材料。 */
(() => {
  'use strict';
  const {esc, api, toast, mountNav, status} = App;
  mountNav('app.html');

  const fileInput = document.querySelector('#file');
  const drop = document.querySelector('#drop');
  const startButton = document.querySelector('#start');
  const yearSelect = document.querySelector('#year');
  const sectionSelect = document.querySelector('#section');
  const preview = document.querySelector('#upload-preview');
  const taskBox = document.querySelector('#task');
  let uploaded = null;
  let busy = false;

  for (let year = 2025; year >= 2006; year -= 1) {
    const option = document.createElement('option');
    option.value = year;
    option.textContent = `${year} 英语（一）${year < 2010 ? '（旧卷）' : ''}`;
    yearSelect.append(option);
  }

  // ---------------------------------------------------------- 上传
  drop.addEventListener('click', event => { if (event.target !== fileInput) fileInput.click(); });
  drop.addEventListener('dragover', event => { event.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', event => {
    event.preventDefault();
    drop.classList.remove('over');
    if (event.dataTransfer.files[0]) upload(event.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', () => { if (fileInput.files[0]) upload(fileInput.files[0]); });

  async function upload(file) {
    if (file.size > 40 * 1024 * 1024) { toast('单个文件不能超过 40 MB', 'bad'); return; }
    const form = new FormData();
    form.append('file', file, file.name);
    preview.innerHTML = `<span class="chip">${esc(file.name)}</span><span class="small muted">上传中…</span>`;
    try {
      const data = await api('/api/upload', {method: 'POST', body: form});
      uploaded = data;
      preview.innerHTML = `<img src="${esc(data.preview)}" alt="" style="width:86px;height:56px;object-fit:cover;border-radius:8px;border:1px solid var(--line)">
        <span class="chip ok">${esc(data.file)}</span>
        <span class="small muted">${(data.bytes / 1024 / 1024).toFixed(2)} MB</span>`;
      startButton.disabled = false;
    } catch (error) {
      uploaded = null;
      startButton.disabled = true;
      preview.innerHTML = `<span class="chip danger">上传失败</span>`;
      toast(error.message, 'bad');
    }
  }

  // ---------------------------------------------------------- 识别
  startButton.addEventListener('click', async () => {
    if (!uploaded || busy) return;
    busy = true;
    startButton.disabled = true;
    startButton.textContent = '识别中…';
    taskBox.hidden = false;
    taskBox.querySelector('span').style.width = '8%';
    document.querySelector('#task-message').textContent = '正在识别文字…';
    try {
      const {task} = await api('/api/extract', {method: 'POST', body: JSON.stringify({
        file: uploaded.file, year: yearSelect.value, section: sectionSelect.value,
      })});
      await follow(task.id);
    } catch (error) {
      toast(error.message, 'bad');
    } finally {
      busy = false;
      startButton.disabled = false;
      startButton.textContent = '开始识别';
    }
  });

  function follow(taskId) {
    return new Promise((resolve, reject) => {
      const tick = async () => {
        let payload;
        try { payload = await api(`/api/task?id=${encodeURIComponent(taskId)}`); }
        catch (error) { reject(error); return; }
        const task = payload.task;
        if (!task) { reject(new Error('识别任务丢失，请重试')); return; }
        taskBox.querySelector('span').style.width = `${task.progress || 10}%`;
        document.querySelector('#task-message').textContent = task.message || '识别中…';
        if (task.state === 'done') { resolve(task); return; }
        if (task.state === 'error') { reject(new Error(task.message || '识别失败')); return; }
        setTimeout(tick, 700);
      };
      tick();
    }).then(task => {
      taskBox.querySelector('span').style.width = '100%';
      document.querySelector('#task-message').textContent = task.message;
      toast(task.message, 'ok');
      location.href = `workbench.html?id=${encodeURIComponent(task.extraction)}`;
    });
  }

  // ---------------------------------------------------------- 阅读材料（粘贴 / 小书签摘录）
  const pasteBox = document.querySelector('#paste');
  const nameInput = document.querySelector('#paste-name');
  const linkInput = document.querySelector('#paste-link');
  const locationInput = document.querySelector('#paste-location');
  const categorySelect = document.querySelector('#paste-category');

  function payloadFromForm() {
    return {
      text: pasteBox.value.trim(),
      name: nameInput.value.trim() || '阅读材料',
      link: linkInput.value.trim(),
      category: categorySelect.value,
      location: locationInput.value.trim(),
    };
  }

  document.querySelector('#paste-go').addEventListener('click', () => {
    const payload = payloadFromForm();
    if (!payload.text) { toast('请先粘贴或摘录要记的段落', 'bad'); return; }
    sessionStorage.setItem('paste-payload', JSON.stringify(payload));
    location.href = 'workbench.html?mode=paste';
  });

  // 常用来源一键填好类型与名称
  document.querySelectorAll('[data-scene]').forEach(chip => chip.addEventListener('click', () => {
    const [category, name] = chip.dataset.scene.split('|');
    categorySelect.value = category;
    if (name) nameInput.value = name;
    else nameInput.focus();
  }));

  // 小书签：复制选中文字并把网址带进本应用
  (function buildBookmarklet() {
    const base = `${location.origin}/workbench.html?mode=capture`;
    const code = `javascript:(function(){var s=String(getSelection()||'').trim();` +
      `try{navigator.clipboard&&navigator.clipboard.writeText(s)}catch(e){}` +
      `var u=location.href,t=document.title||'';` +
      `window.open(${JSON.stringify(base)}+'&url='+encodeURIComponent(u)+'&title='+encodeURIComponent(t)+` +
      `'&text='+encodeURIComponent(s.slice(0,6000)),'_blank');})()`;
    const anchor = document.querySelector('#bookmarklet');
    if (anchor) anchor.setAttribute('href', code);
  })();

  // 小书签跳转过来时，自动把内容填好
  (function readCaptureParams() {
    const params = new URLSearchParams(location.search);
    if (params.get('mode') !== 'capture') return;
    const text = params.get('text') || '';
    const url = params.get('url') || '';
    const title = params.get('title') || '';
    if (text) pasteBox.value = text;
    if (url) linkInput.value = url;
    if (title) nameInput.value = title.slice(0, 80);
    if (url) {
      try {
        const host = new URL(url).hostname.replace(/^www\./, '');
        categorySelect.value = /nytimes|economist|guardian|bbc|cnn|reuters|wsj|ft\.com|newyorker|atlantic/.test(host)
          ? 'news' : categorySelect.value;
        if (!nameInput.value) nameInput.value = host;
      } catch (error) { /* 无效链接忽略 */ }
    }
    history.replaceState(null, '', 'app.html');
    const hint = document.createElement('div');
    hint.className = 'notice';
    hint.innerHTML = text
      ? '已从浏览器摘录这段文字，确认来源信息后点“整理这段文字”。'
      : '已带上当前网址。请在文章里选中句子后重新点小书签，或手动粘贴要记的段落。';
    document.querySelector('.page-head').append(hint);
    pasteBox.focus();
  })();

  // ---------------------------------------------------------- 状态
  status().then(data => {
    document.querySelector('#engine-chip').textContent = {
      'apple-vision': '识别引擎：macOS Vision',
      tesseract: '识别引擎：Tesseract',
      none: '无识别引擎',
    }[data.engine] || '识别引擎：未知';
    document.querySelector('#engine-chip').className = 'chip ' + (data.engine === 'none' ? 'danger' : 'ok');
    document.querySelector('#dict-state').textContent = data.dictionary
      ? `已内置 ${data.dictionary_words.toLocaleString()} 个词条`
      : '未安装（可运行 build_dict.py 生成）';
    const labels = {exam: '真题试卷', news: '外刊文章', book: '书籍', other: '其他材料'};
    const parts = Object.entries(data.library.categories || {})
      .filter(([, count]) => count > 0)
      .map(([key, count]) => `${labels[key] || key} ${count}`);
    document.querySelector('#lib-summary').textContent =
      `共 ${data.library.total} 条记录（${parts.join(' · ')}）；原有 ${data.library.main} 条，工作台新增 ${data.library.additions} 条`;
    if (data.pending?.length) {
      const box = document.createElement('div');
      box.className = 'notice';
      box.innerHTML = `待整理清单里有 <b>${data.pending.length}</b> 个词：
        ${data.pending.slice(0, 12).map(item => esc(item.word)).join('、')}
        <a href="workbench.html?mode=pending">去整理</a>`;
      document.querySelector('.page-head').append(box);
    }
    const recent = document.querySelector('#recent');
    if (!data.extractions?.length) {
      recent.innerHTML = '<div class="empty">还没有识别过的材料。上传一张做过标记的试卷试试。</div>';
      return;
    }
    recent.innerHTML = data.extractions.slice(0, 6).map(id =>
      `<a class="card" style="display:flex;gap:12px;align-items:center;text-decoration:none;color:inherit"
          href="workbench.html?id=${encodeURIComponent(id)}">
        <span class="chip accent">识别结果</span>
        <span class="mono">${esc(id)}</span>
        <span class="spacer"></span><span class="small muted">打开核对 →</span></a>`).join('');
  }).catch(error => {
    document.querySelector('#engine-chip').textContent = '服务未连接';
    document.querySelector('#engine-chip').className = 'chip danger';
    toast(`本机服务没有响应：${error.message}`, 'bad');
  });
})();
