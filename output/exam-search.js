/* 真题检索只读：不写入生词、学习记录或浏览器存储。 */
(() => {
  'use strict';
  const data = window.EXAM_BANK;
  const year = document.getElementById('exam-year');
  const section = document.getElementById('exam-section');
  const word = document.getElementById('exam-word');
  const status = document.getElementById('status');
  const results = document.getElementById('results');
  const more = document.getElementById('more');
  if (!data) { status.textContent = '题库数据加载失败，请重新运行 python main.py。'; return; }
  const names = {cloze:'完形填空',text1:'阅读 Text 1',text2:'阅读 Text 2',text3:'阅读 Text 3',text4:'阅读 Text 4',new_type:'新题型',translation:'翻译',writing_a:'小作文',writing_b:'大作文'};
  const kinds = {passage:'正文原段',paragraph_option:'新题型待选段落',question:'题干',option:'选项 · 不代表正确答案',directions:'作答说明',writing:'写作题目'};
  const priority = {passage:0,paragraph_option:1,question:2,option:3,writing:4,directions:5};
  let matches = [], shown = 0, matcher;
  for (const paper of data.papers.slice().reverse()) {
    const option = document.createElement('option'); option.value = paper.year; option.textContent = paper.year + (paper.year < 2010 ? ' 旧卷' : ' 英语一'); year.append(option);
  }
  const params = new URLSearchParams(location.search);
  if (data.papers.some(p => String(p.year) === params.get('year'))) year.value = params.get('year');
  const currentPaper = () => data.papers.find(p => String(p.year) === year.value);
  function updateSources() {
    const paper = currentPaper();
    document.getElementById('local-paper').href = `exams/${paper.year}.html`;
    document.getElementById('source-pdf').href = '../' + paper.pdf;
    document.getElementById('online-source').href = paper.source_url;
  }
  function appendText(container, text) {
    let last = 0; matcher.lastIndex = 0;
    for (const match of text.matchAll(matcher)) {
      container.append(document.createTextNode(text.slice(last, match.index)));
      const mark = document.createElement('mark'); mark.textContent = match[0]; container.append(mark);
      last = match.index + match[0].length;
    }
    container.append(document.createTextNode(text.slice(last)));
  }
  function renderMore() {
    const paper = currentPaper();
    for (const record of matches.slice(shown, shown + 40)) {
      const item = document.createElement('article'); item.className = 'result';
      const where = document.createElement('p'); where.className = 'where';
      where.textContent = `${paper.year} · ${names[record.section]} · ${record.location}　`;
      const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = kinds[record.kind]; where.append(tag);
      const text = document.createElement('p'); text.className = 'text'; text.lang = 'en'; appendText(text, record.text);
      const link = document.createElement('a'); link.href = `exams/${paper.year}.html#${record.anchor}`; link.textContent = '在本地整卷中核对';
      item.append(where, text, link); results.append(item);
    }
    shown = Math.min(shown + 40, matches.length); more.hidden = shown >= matches.length;
  }
  function lookup(event) {
    if (event) event.preventDefault();
    document.getElementById('dictionary-link').href='查词与收词.html?'+new URLSearchParams({word:word.value.trim(),year:year.value,section:section.value});
    updateSources(); results.replaceChildren(); more.hidden = true; shown = 0;
    const query = word.value.trim();
    if (!query) { status.textContent = '请选择年份并输入一个单词或短语。'; return; }
    const forms = [...new Set([query, ...(data.aliases[query.toLowerCase()] || [])])];
    const escaped = forms.sort((a,b) => b.length-a.length).map(value => value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&').replace(/\s+/g,'\\s+'));
    matcher = new RegExp('(?<![A-Za-z])(?:' + escaped.join('|') + ')(?![A-Za-z])','gi');
    matches = currentPaper().records.filter(record => {
      matcher.lastIndex = 0;
      return (!section.value || record.section === section.value) && matcher.test(record.text);
    }).sort((a,b) => priority[a.kind] - priority[b.kind]);
    status.textContent = matches.length ? `找到 ${matches.length} 处原段／题干／选项。匹配词形：${forms.join(' / ')}` : '未找到。请核对年份、英语一/二、拼写，或尝试输入原文词形；不会为未找到的词编造例句。';
    renderMore();
  }
  document.getElementById('lookup').addEventListener('submit', lookup);
  year.addEventListener('change', lookup); section.addEventListener('change', lookup); more.addEventListener('click', renderMore);
  updateSources();
  if(params.get('word')){word.value=params.get('word');lookup();}
})();
