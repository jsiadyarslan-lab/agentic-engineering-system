/* Agentic Engineering System — عارض Markdown متدفق (الأمر 008 §4+§28-§29).
 * عارض مدمج صفر تبعيات: عناوين/قوائم/جداول/أسوار كود/كود سطري/روابط/
 * غامق/مائل — آمن للبث (escape-first ثم بناء)، وRTL للمحتوى العربي مع
 * dir=ltr قسري للكود والروابط وJSON حتى لا تتشوه الأقواس (§29).
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------- سطري: كود ثم روابط ثم غامق/مائل ----------
  function inline(text) {
    var out = esc(text);
    out = out.replace(/`([^`]+)`/g, function (_m, code) {
      return '<code class="md-code" dir="ltr">' + code + "</code>";
    });
    out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, function (_m, label, url) {
      return '<a href="' + url + '" target="_blank" rel="noopener" dir="ltr">' + label + "</a>";
    });
    out = out.replace(/(^|[\s(])((?:https?:\/\/)[^\s<)]+)/g, function (_m, pre, url) {
      return pre + '<a href="' + url + '" target="_blank" rel="noopener" dir="ltr">' + url + "</a>";
    });
    out = out.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>");
    return out;
  }

  // ---------- بلوكات ----------
  function renderBlocks(lines) {
    var html = [];
    var i = 0;
    var listStack = null; // "ul" | "ol"

    function closeList() {
      if (listStack) { html.push("</" + listStack + ">"); listStack = null; }
    }

    while (i < lines.length) {
      var line = lines[i];

      // سور كود — مفتوح أثناء البث يُغلق مؤقتًا (لا وميض كسير §4)
      if (/^\s*```/.test(line)) {
        closeList();
        var codeLines = [];
        i++;
        var closed = false;
        while (i < lines.length) {
          if (/^\s*```/.test(lines[i])) { closed = true; i++; break; }
          codeLines.push(lines[i]);
          i++;
        }
        html.push('<pre class="md-pre" dir="ltr"><code>' +
          esc(codeLines.join("\n")) +
          (closed ? "" : "▌") + "</code></pre>");
        continue;
      }

      var h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        closeList();
        var level = h[1].length;
        html.push("<h" + (level + 1) + ' class="md-h">' + inline(h[2]) + "</h" + (level + 1) + ">");
        i++;
        continue;
      }

      if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
        closeList();
        html.push('<hr class="md-hr">');
        i++;
        continue;
      }

      // جدول: صف فاصل |---|---| بعد صف رأس
      if (/\|/.test(line) && i + 1 < lines.length &&
          /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
        closeList();
        var head = splitRow(line);
        i += 2;
        var body = [];
        while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) {
          body.push(splitRow(lines[i]));
          i++;
        }
        html.push('<div class="md-table-wrap" dir="ltr"><table class="md-table"><thead><tr>' +
          head.map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") +
          "</tr></thead><tbody>" +
          body.map(function (row) {
            return "<tr>" + row.map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>";
          }).join("") + "</tbody></table></div>");
        continue;
      }

      var ul = line.match(/^\s*[-*•]\s+(.*)$/);
      var ol = line.match(/^\s*(\d+)[.)]\s+(.*)$/);
      if (ul || ol) {
        var want = ul ? "ul" : "ol";
        if (listStack !== want) { closeList(); html.push("<" + want + ' class="md-list">'); listStack = want; }
        html.push("<li>" + inline(ul ? ul[1] : ol[2]) + "</li>");
        i++;
        continue;
      }

      var quote = line.match(/^\s*>\s?(.*)$/);
      if (quote) {
        closeList();
        html.push('<blockquote class="md-quote">' + inline(quote[1]) + "</blockquote>");
        i++;
        continue;
      }

      if (!line.trim()) { closeList(); i++; continue; }

      closeList();
      // فقرة: تُجمع الأسطر المتتالية غير الفارغة
      var para = [line];
      i++;
      while (i < lines.length && lines[i].trim() &&
             !/^\s*(```|#{1,4}\s|[-*•]\s|\d+[.)]\s|>)/.test(lines[i]) &&
             !/\|/.test(lines[i])) {
        para.push(lines[i]);
        i++;
      }
      html.push('<p class="md-p">' + para.map(inline).join("<br>") + "</p>");
    }
    closeList();
    return html.join("");
  }

  function splitRow(line) {
    return line.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); });
  }

  window.MD = {
    esc: esc,
    /** عرض كامل — خيار streaming يضيف مؤشر كتابة في النهاية. */
    render: function (text, opts) {
      var lines = String(text == null ? "" : text).split(/\r?\n/);
      var body = renderBlocks(lines);
      if (opts && opts.streaming && body) {
        body += '<span class="md-caret">▌</span>';
      }
      return body;
    }
  };
})();
