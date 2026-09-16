# 试卷识别与本机应用（vocabulary_app）

这一部分把“上传做过标记的试卷 → 自动找出被圈被划的词 → 核对后写进生词本”做成一个
本机应用。全部计算在本机完成，不联网、不上传材料。

## 怎么启动

```bash
# macOS / Linux
./启动生词本.sh            # 或双击 启动生词本.command

# Windows
启动生词本.bat
```

启动后浏览器会自动打开 `http://127.0.0.1:8765`。服务只监听 127.0.0.1，
按 `Control+C` 或关掉终端窗口即停止。

只想复习、不做识别时不需要启动服务，直接打开 `output/index.html` 即可。

## 目录与职责

```text
vocabulary_app/
├─ server.py             本机 HTTP 服务：页面、上传、识别、查词、保存、重新生成
├─ recognize.py          识别主流程：OCR → 版面重建 → 圈画判定 → 题库比对
├─ ink.py                墨迹与圈画几何分析、词图裁剪
├─ dictionary.py         词典查询（复用仓库里的 data/dictionary 分片生成 SQLite）
├─ personal_cards.py     个人词库卡片：与 assets/personal-core.js 逐字一致的校验与编号
├─ store.py              生词库读写：新词写 additions，主词库保持只读
├─ build_dict.py         从 data/dictionary 分片（或 ECDICT CSV）生成查询库
└─ engine/VisionEngine.swift   macOS 文字识别与 PDF 渲染引擎（Swift + Vision + PDFKit）
```

## 与仓库既有功能的关系

- **词典只有一份**：`data/dictionary/` 是浏览器端的 ECDICT 分片（`assets/dictionary.js` 用），
  本机服务用 `build_dict.py` 把它转成 `data/dict/dict.sqlite`（约 35MB，已在 .gitignore）。
  首次运行“启动生词本”会自动生成一次，约 2 秒。
- **收词进个人词库**：工作台保存时，除了写入 `data/vocabulary_additions.json` 生成复习页面，
  还会按 `PersonalCore` 的规则生成“个人词条卡片”，由 `main.py` 发布为
  `output/personal-cards.js`；页面上的 `personal-library.js` 会在启动时把这些卡片
  并入浏览器里的个人词库（与用户自己收的词合在一起，按词义去重）。
- **卡片必须合法**：`personal-core.js` 的 `validateCards()` 只要遇到一张坏卡片就会整体抛错，
  所以 `personal_cards.py` 复刻了同一套编号与长度规则，`tests/test_personal_cards.py`
  会把生成的卡片交给真正的 JS 实现再验一遍；页面上也逐张校验，坏卡片只跳过不拖垮全库。

## 识别流程

1. **取文字**：PDF 走内置引擎渲染成页面图；照片先按文字框形状判断方向，
   横放的照片会自动转正。文字识别用 macOS Vision；没有该引擎时回退 Tesseract。
2. **切词**：Vision 只给行框，这里用墨迹纵向投影找词间空格，得到与图片对齐的词框；
   投影切分与识别文本数量不一致时回退到按字符宽度估算。
3. **找笔迹**：用文字框把印刷正文挖掉，剩下的墨迹做连通域标记，只可能是笔迹。
   再用笔画长度图还原完整形状，按空心（圈）、细长横条（下划线／荧光笔）、
   成片涂画分类。判据要求笔迹比印刷文字更大更粗，避免把印刷字母当成标记。
4. **归属到词**：笔迹要横向罩住整个词、落在同一行、纵向贴得足够近，才算这个词被标记。
   一个圈跨两个词时会同时命中，只有最贴合的那个默认勾选，其余标为“请确认”。
5. **回到真题**：用句子文本在本地 20 套真题库里比对（阈值 0.62），命中后补上
   年份、题型、段落、原句与整卷锚点；比对不上就按你的材料原文收录，不编造例句。
6. **补释义**：已经录入生词本的词显示原有释义；新词用离线词典给出音标与候选词义，
   由你在工作台挑选或改写。

识别强度分三档（工作台顶部的“只看有圈画证据的词”配合使用）：

| 档位 | 行为 |
| --- | --- |
| strict | 只保留明显的圈与长下划线 |
| standard（默认） | 圈、下划线、荧光笔，要求笔迹比印刷字更大更粗 |
| loose | 放宽尺寸与笔画要求，候选更多，适合标注很轻的铅笔痕迹 |

## 阅读场景与来源字段

一份材料有 `category`：`exam`（真题试卷）、`news`（外刊文章）、`book`（书籍）、`other`（其他）。
它决定来源分组标题（`外刊文章｜纽约时报`）与生词本里的筛选分类。

| 字段 | 含义 |
| --- | --- |
| `category` | 场景分类，决定分组与筛选 |
| `source_name` | 来源名称，如纽约时报、Sapiens |
| `link` | 原文链接，只保留 http/https，并去掉 utm_* 等跟踪参数 |
| `location` | 位置说明，如「第 3 段」「第 5 章」 |
| `capture` | 来源方式：photo（识别）／text（粘贴或小书签摘录） |
| `captured_at` | 摘录日期 |

`candidates_from_text()` 同时服务三种输入：外刊段落、书页文字、真题文字。
只有带年份、或句子长度 ≥60 字符时才去题库比对位置——外刊里的短句容易和真题某句
「看起来像」，宁可不去套，也不给出错误出处。题库比对只认正文与待选段落，
不认题干和选项（选项常常只有一两个词，会误命中）。

浏览器小书签把「选中文字 + 当前网址 + 标题」通过 URL 参数送进工作台（`?mode=capture`），
不经过网络请求，因此在 https 页面上也能用。

## 查词的两级规则

这是刻意的产品规则，避免把试卷里的普通词都变成生词：

- **已录入生词本**：显示词义、原句、位置，可朗读、可直接进入练习。
- **未录入生词本**：只显示它在真题里的位置与上下文，**不给释义**；
  需要收录时点“加入待整理清单”，回到工作台补全原句与释义。

## 数据约定

- `data/vocabulary.json`：原有词库，应用只读，不修改、不重置熟悉程度。
- `data/vocabulary_additions.json`：工作台新增的词条；`python3 main.py` 会把它合并进页面。
  删除该文件即回到原状。
- `data/pending_words.json`：查词时“加入待整理”的词，不算生词。
- `data/uploads/`：上传的原始材料（inbox/）与识别结果、整页图、词图。
- `data/dict/dict.sqlite`：离线词典，由 `build_dict.py` 生成。

新增词条沿用主词库字段，并额外保存 `exam_record_id`、`page`、`mark_kind`、`crop`，
方便回到原文核对。词形变化必须是原文出现过的形式，否则写入会被拒绝。

## 重新生成词典

```bash
curl -L -o /tmp/ecdict.csv https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv
python3 vocabulary_app/build_dict.py /tmp/ecdict.csv
```

## 重新编译识别引擎（仅 macOS）

```bash
swiftc -O vocabulary_app/engine/VisionEngine.swift -o vocabulary_app/engine/vision_engine
```

`vision_engine probe` 可以自检；`vision_engine ocr <图片或PDF> --work-dir <目录>`
输出逐行文字与词框，并在目录里写出整页图、墨迹图与笔画长度图，便于排查识别问题。

## 验证

```bash
python3 -m unittest discover -s tests -v      # 含识别、工作台、前端脚本检查
```

`tests/test_recognition.py` 会用本地整卷 PDF 渲染一页，在真实位置画圈和画线，
再跑完整流程，确认“标了的词找得到、没标的词不会误报”。
