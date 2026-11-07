/* Pure message presentation, shared by history and incremental updates. */
function svgIcon(name, cls) {
  return '<svg class="icon' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24"><use href="#i-' + name + '"/></svg>';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

// 高亮词法片段。用正则字面量 + .source 拼装，避免 new RegExp 里的双重转义。
var HL_STR_RE = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/;
var HL_KWD_RE = /\b(?:def|class|return|import|from|if|elif|else|for|while|try|except|finally|async|await|with|as|lambda|yield|function|const|let|var|switch|case|break|continue|default|new|throw|typeof|instanceof|interface|type|enum|public|private|static|void|int|string|bool|SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|GROUP|ORDER|BY|LIMIT|CREATE|TABLE)\b/;
var HL_NUM_RE = /\b\d+(?:\.\d+)?\b/;
var HL_HASH_LANGS = /^(?:py|python|bash|sh|shell|zsh|yaml|yml|rb|ruby|toml|ini|conf|dockerfile|makefile)$/;

function hlRegex(commentRe) {
  return new RegExp(
    "(" + HL_STR_RE.source + ")|(" + commentRe.source + ")|(" +
    HL_KWD_RE.source + ")|(" + HL_NUM_RE.source + ")", "g");
}
var HL_RE_HASH = hlRegex(/#[^\n]*/);
var HL_RE_SLASH = hlRegex(/\/\/[^\n]*|\/\*[\s\S]*?\*\//);

// 单遍扫描"原始源码"，只在拼接时对叶子文本转义。
// 旧实现是先整体 escapeHtml、再对结果反复 replace，于是自己注入的
// <span class="hl-str"> 会被关键字表里的 class 再匹配一次（产出
// <span <span class="hl-kwd">class</span>="hl-str">），转义出来的 &#39;
// 里的 39 也会被数字规则吃掉。扫原文就没有这两类自噬。
function highlightCode(code, lang) {
  lang = (lang || "").toLowerCase().trim();
  var re = HL_HASH_LANGS.test(lang) ? HL_RE_HASH : HL_RE_SLASH;
  var out = "", last = 0, m;
  re.lastIndex = 0;   // 模块级 /g 正则跨调用复用，必须重置
  while ((m = re.exec(code)) !== null) {
    out += escapeHtml(code.slice(last, m.index));
    var cls = m[1] ? "hl-str" : m[2] ? "hl-cmt" : m[3] ? "hl-kwd" : "hl-num";
    out += '<span class="' + cls + '">' + escapeHtml(m[0]) + "</span>";
    last = m.index + m[0].length;
  }
  return out + escapeHtml(code.slice(last));
}

var ALLOWED = {
  B:1, STRONG:1, I:1, EM:1, U:1, INS:1, S:1, STRIKE:1, DEL:1, CODE:1, PRE:1, BR:1, A:1, BLOCKQUOTE:1,
  TABLE:1, THEAD:1, TBODY:1, TR:1, TH:1, TD:1, DIV:1, SPAN:1, P:1,
  H1:1, H2:1, H3:1, H4:1, H5:1, H6:1, UL:1, OL:1, LI:1, HR:1,
  // Telegram 原生剧透 / 自定义 emoji：渲染器当前不产出，但模型可能原样输出。
  // 收进白名单后剧透文字才不会被“拆标签”直接摊开（配合 CSS 模糊 + 点击揭示）；
  // 自定义元素在 HTML 文档里 tagName 会大写化，故键名写成 TG-SPOILER/TG-EMOJI。
  "TG-SPOILER":1, "TG-EMOJI":1
};

// 把 marked 的标准输出对齐到本项目既有的 CSS，省得为了一个解析器去改整套样式。
// 三件事都必须在"剥属性"之前做完——align / style / type 随后都会被清掉。
function normalizeMarkdownNode(c) {
  // 1) GFM 任务列表：marked 出 <input type=checkbox disabled>，本项目是 .task-checkbox
  if (c.tagName === "INPUT") {
    if (c.getAttribute("type") !== "checkbox") return false;
    // 用 hasAttribute 而不是 .checked：marked 出的是 checked 属性，
    // 而 .checked 这个 IDL 属性在非浏览器 DOM 实现里不一定跟着属性走。
    var checked = c.hasAttribute("checked");
    var box = document.createElement("span");
    box.className = "task-checkbox" + (checked ? " checked" : "");
    if (checked) box.textContent = "✓";
    var li = c.parentNode;
    c.parentNode.replaceChild(box, c);
    // 样式挂在 .task-item 上，而 marked 并不给 <li> 加 class（松散列表时
    // checkbox 还会多包一层 <p>），所以往上找到 LI 自己补。
    while (li && li.tagName !== "LI") li = li.parentNode;
    if (li && li.classList) li.classList.add("task-item");
    return true;   // 已替换，调用方不要再往下走
  }
  // 2) 任务项样式类对齐（部分 marked 版本会给 task-list-item）
  if (c.tagName === "LI" && c.classList.contains("task-list-item")) c.classList.add("task-item");
  // 3) 表格列对齐：属性会被剥掉，先落到 class 上
  if (c.tagName === "TH" || c.tagName === "TD") {
    var al = c.getAttribute("align") || (c.style && c.style.textAlign);
    if (al) c.classList.add("ta-" + al);
  }
  // 4) 宽表格的横向滚动容器。marked 只出裸 <table>，而 overflow-x 挂在
  //    .table-wrap 上，少了它宽表格会直接撑破气泡。
  if (c.tagName === "TABLE" && !(c.parentNode && c.parentNode.className === "table-wrap")) {
    var tw = document.createElement("div");
    tw.className = "table-wrap";
    c.parentNode.insertBefore(tw, c);
    tw.appendChild(c);
  }
  return false;
}

function sanitizeHtml(htmlStr) {
  // Parse inertly: a detached DIV can still fetch IMG URLs and fire onerror
  // before its forbidden attributes/nodes are removed. Template contents cannot.
  var tmp = document.createElement("template");
  tmp.innerHTML = String(htmlStr);
  (function clean(node) {
    Array.prototype.slice.call(node.childNodes).forEach(function (c) {
      if (c.nodeType === 3) return;
      if (c.nodeType !== 1) { node.removeChild(c); return; }
      if (/^(SCRIPT|STYLE|IFRAME|OBJECT|EMBED|SVG|MATH|TEMPLATE|LINK|META)$/.test(c.tagName)) {
        node.removeChild(c);
        return;
      }
      if (normalizeMarkdownNode(c)) return;
      if (!ALLOWED[c.tagName]) {
        clean(c);
        var frag = document.createDocumentFragment();
        while (c.firstChild) frag.appendChild(c.firstChild);
        c.parentNode.replaceChild(frag, c);
        return;
      }
      Array.prototype.slice.call(c.attributes).forEach(function (a) {
        if (c.tagName === "A" && a.name === "href") {
          if (!/^(https?:|mailto:)/i.test(a.value)) c.removeAttribute(a.name);
        } else if (c.tagName === "A" && (a.name === "target" || a.name === "rel")) {
        } else if (c.tagName === "BLOCKQUOTE" && (a.name === "expandable" || a.name === "data-raw" || a.name === "data-output-path" || ['data-protocol','data-state','data-preview','data-operation-details'].includes(a.name) || (a.name === "data-web-fold" && a.value === "1") || (a.name === "data-compact" && a.value === "1"))) {
          // 保留：服务端 render_folded_html 用 <blockquote expandable> 标记
          // 「可展开折叠的协议代码块」（与电报原生 expandable 同源），网页据此做
          // 折叠交互（CSS blockquote[expandable] + bindContentClicks 里的点击切换）。
        } else if (a.name === "class") {
          var classes = a.value.split(/\s+/).filter(function (name) {
            return /^(language-[a-zA-Z0-9_+#.-]+|ta-(left|center|right)|task-item|task-checkbox|checked|table-wrap|file-delivery-note|file-write-result|stop-notice)$/.test(name);
          });
          if (classes.length) c.setAttribute("class", classes.join(" "));
          else c.removeAttribute("class");
        } else {
          c.removeAttribute(a.name);
        }
      });
      if (c.tagName === "A") { c.target = "_blank"; c.rel = "noopener noreferrer"; }
      clean(c);
    });
  })(tmp.content);
  return tmp.innerHTML;
}

function htmlWithLineBreaks(htmlStr) {
  var tmp = document.createElement("div");
  tmp.innerHTML = htmlStr;
  (function visit(node) {
    if (/^(PRE|CODE)$/.test(node.tagName)) return;
    Array.prototype.slice.call(node.childNodes).forEach(function (c) {
      if (c.nodeType === 1) { visit(c); return; }
      if (c.nodeType !== 3 || c.nodeValue.indexOf("\n") < 0) return;
      if (/^(TABLE|THEAD|TBODY|TR|UL|OL)$/.test(node.tagName)) return;
      // Formatting whitespace next to a block is not another visible blank
      // paragraph. Leave the original text node intact instead of adding BRs.
      if (/^\s*$/.test(c.nodeValue) && [c.previousSibling,c.nextSibling].some(function(s){
        return s && /^(PRE|BLOCKQUOTE|DIV|TABLE|UL|OL|P|H[1-6]|HR)$/.test(s.tagName);
      })) return;
      var frag = document.createDocumentFragment();
      c.nodeValue.split("\n").forEach(function (line, i) {
        if (i) frag.appendChild(document.createElement("br"));
        frag.appendChild(document.createTextNode(line));
      });
      c.parentNode.replaceChild(frag, c);
    });
  })(tmp);
  return tmp.innerHTML;
}

// GFM 解析交给 marked（本地 vendor，不联网）。breaks:true 是必须的：
// Agent / 聊天输出严重依赖单换行可见，旧渲染器把每个 \n 都转成了 <br>，
// 用 GFM 默认的 breaks:false 会让大量既有输出塌成一段。
if (window.marked && marked.use) {
  marked.use({ gfm: true, breaks: true });
}

function renderMarkdown(src) {
  if (window.marked && marked.parse) {
    try { return marked.parse(src); } catch (e) { /* 落到下面的纯文本兜底 */ }
  }
  return escapeHtml(src).replace(/\n/g, "<br>");
}

function renderText(text, parseMode) {
  text = text == null ? "" : String(text);
  if (parseMode && String(parseMode).toUpperCase().indexOf("HTML") >= 0) {
    return htmlWithLineBreaks(sanitizeHtml(text));
  }

  // marked 直接出 <pre><code class="language-xxx">，正好是 enhanceBubbleContent
  // 期待的形状（它按 /language-(...)/ 读语言并补外壳），所以这里不再需要
  // 旧的 %%CODE_BLOCK_n%% 占位符回填——那个用字符串做 replace 的 pattern，
  // 代码里出现 $& / $` / $' / $$ 会被当成替换模式吃掉。
  return sanitizeHtml(renderMarkdown(text));
}

// 用户气泡永远按字面渲染：只转义 + 换行，绝不过 marked / HTML，免得输入里的
// *、`、#、| 之类被当 markdown 语法篡改显示（Telegram/CLI 两端都原样回显用户
// 输入，Web 对齐）。其余角色照常走 renderText。初始渲染(makeBubble)与流式/编辑
// 更新(putTextFrame)两处共用，避免规则失步。
function renderBubbleBody(role, text, parseMode, webDisplay) {
  if(webDisplay?.version===1 && typeof webDisplay.plain_text==='string'){
    return escapeHtml(webDisplay.plain_text).replace(/\n/g,'<br>');
  }
  if (role === "user") {
    return escapeHtml(text == null ? "" : String(text)).replace(/\n/g, "<br>");
  }
  // Reported errors are literal diagnostics both live and in durable history.
  // Do not turn upstream Markdown, HTML or stack traces into different layouts.
  if(role==='sys'&&!parseMode&&/^⚠️(?:\s|$)/.test(String(text||''))){
    return escapeHtml(String(text||'')).replace(/\n/g,'<br>');
  }
  if(webDisplay?.version===1 && Array.isArray(webDisplay.segments) &&
     webDisplay.segments.every(s=>s && ['markdown','html'].includes(s.kind) && typeof s.text==='string')){
    // Every segment uses the same allowlist. Never trust even stored/tool HTML.
    let rendered=webDisplay.segments.map(s=>Number.isSafeInteger(s.visual_index)&&s.visual_index>=0&&s.visual_index<4?
      '<div class="visual-output-slot" data-visual-index="'+s.visual_index+'"><section class="visual-page visual-page-loading" aria-busy="true"><header><span class="visual-page-identity"><strong>'+escapeHtml(s.visual_title||s.text.replace(/<[^>]+>/g,'').replace(/ · 生成中…$/,''))+'</strong></span><span class="visual-page-phase" role="status">'+(s.visual_pending?'生成中…':'准备预览…')+'</span></header><div class="visual-page-viewport"><div class="visual-page-skeleton" aria-hidden="true"><span></span><span></span><span></span></div></div></section></div>':
      s.footer?'<div class="token-hud">'+renderText(s.text,'HTML')+'</div>':renderText(s.text,s.kind==='html'?'HTML':null)).join('\n');
    return rendered;
  }
  const rendered=renderText(text,parseMode);
  return role==='sys'?rendered.replace(/<pre(?:\s[^>]*)?>/g,'<pre class="literal-diagnostic">'):rendered;
}


export {svgIcon,escapeHtml,highlightCode,sanitizeHtml,htmlWithLineBreaks,renderMarkdown,renderText,renderBubbleBody};
