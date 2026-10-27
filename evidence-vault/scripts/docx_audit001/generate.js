/* AES-AUDIT-001 — Arabic RTL docx: comprehensive audit + harsh critique + dsh comparison + roadmap.
 * Follows docx skill: R2 cover (centered, direction-safe), 3-section numbering,
 * TOC 3-step, WPS-compat tables (PERCENTAGE + margins + CLEAR shading).
 * Proven pattern: docx_013 generator (passed postcheck). */
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  ImageRun, PageBreak, Header, Footer, PageNumber, NumberFormat,
  AlignmentType, HeadingLevel, WidthType, BorderStyle, ShadingType,
  SectionType, TableOfContents, LevelFormat, TableLayoutType,
} = require("docx");
const fs = require("fs");

const OUT = "/home/z/my-project/download/AES-AUDIT-001-Comprehensive-Audit-Report.docx";

/* ---------- palette (AES identity: charcoal + agent blue) ---------- */
const P = {
  bg: "0B0E14", accent: "58A6FF", title: "F0F3F6", subtitle: "A6B0BC",
  meta: "A6B0BC", footer: "7D8794", primary: "16202E", body: "24303E",
  secondary: "5B6B7D", surface: "F0F5FE", tableHead: "EDF1F6",
  border: "9AA6B2", inner: "D8DEE6",
};
const AR = { ascii: "Segoe UI", hAnsi: "Segoe UI", cs: "Segoe UI" };
const MONO = { ascii: "Consolas", hAnsi: "Consolas", cs: "Consolas" };
const NB = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: NB, bottom: NB, left: NB, right: NB };
const allNoBorders = { top: NB, bottom: NB, left: NB, right: NB, insideHorizontal: NB, insideVertical: NB };

/* ---------- inline markup: `code` -> mono LTR runs ---------- */
function mkRuns(text, o = {}) {
  const size = o.size || 24;
  const runs = [];
  const parts = String(text).split("`");
  for (let i = 0; i < parts.length; i++) {
    if (parts[i] === "") continue;
    if (i % 2 === 1) {
      runs.push(new TextRun({
        text: parts[i], font: MONO, size: Math.max(size - 2, 16),
        sizeComplexScript: Math.max(size - 2, 16), color: o.color || "3D5A80",
      }));
    } else {
      runs.push(new TextRun({
        text: parts[i], rightToLeft: true, font: AR, size, sizeComplexScript: size,
        bold: o.bold || undefined, color: o.color || P.body,
      }));
    }
  }
  return runs;
}

/* ---------- block builders ---------- */
function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1, bidirectional: true, alignment: AlignmentType.START,
    spacing: { before: 360, after: 160, line: 380, lineRule: "atLeast" },
    children: mkRuns(text, { size: 32, bold: true, color: P.primary }),
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2, bidirectional: true, alignment: AlignmentType.START,
    spacing: { before: 260, after: 120, line: 340, lineRule: "atLeast" },
    children: mkRuns(text, { size: 28, bold: true, color: P.primary }),
  });
}
function para(text) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.JUSTIFIED,
    spacing: { line: 312, after: 120 },
    children: mkRuns(text, { size: 24 }),
  });
}
function callout(text) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.JUSTIFIED,
    shading: { type: ShadingType.CLEAR, fill: P.surface },
    border: { right: { style: BorderStyle.SINGLE, size: 24, color: P.accent, space: 8 } },
    indent: { left: 200, right: 200 },
    spacing: { line: 312, before: 160, after: 160 },
    children: mkRuns(text, { size: 24 }),
  });
}
function caption(text) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 200, line: 280 },
    children: mkRuns(text, { size: 20, color: P.secondary }),
  });
}
function tableCaption(text) {
  return new Paragraph({
    bidirectional: true, alignment: AlignmentType.START, keepNext: true,
    spacing: { before: 160, after: 80, line: 280 },
    children: mkRuns(text, { size: 21, bold: true, color: P.secondary }),
  });
}

/* PNG header size reader (IHDR) */
function readPngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}
function imageBlock(src, displayW, capText) {
  const { w, h } = readPngSize(src);
  const dh = Math.round(displayW * (h / w));
  return [
    new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { before: 160 },
      children: [new ImageRun({ data: fs.readFileSync(src), transformation: { width: displayW, height: dh }, type: "png" })],
    }),
    caption(capText),
  ];
}

/* RTL table: visuallyRightToLeft -- first defined column renders on the RIGHT */
function tableBlock(header, rows, widths) {
  const trs = [];
  trs.push(new TableRow({
    tableHeader: true, cantSplit: true,
    children: header.map((t, i) => new TableCell({
      width: { size: widths[i], type: WidthType.PERCENTAGE },
      shading: { type: ShadingType.CLEAR, fill: P.tableHead },
      margins: { top: 70, bottom: 70, left: 110, right: 110 },
      children: [new Paragraph({
        bidirectional: true, alignment: AlignmentType.START, spacing: { line: 290 },
        children: mkRuns(t, { size: 21, bold: true, color: P.primary }),
      })],
    })),
  }));
  for (const r of rows) {
    trs.push(new TableRow({
      cantSplit: true,
      children: r.map((t, i) => new TableCell({
        width: { size: widths[i], type: WidthType.PERCENTAGE },
        margins: { top: 60, bottom: 60, left: 110, right: 110 },
        children: [new Paragraph({
          bidirectional: true, alignment: AlignmentType.START, spacing: { line: 290 },
          children: mkRuns(t, { size: 21, color: P.body }),
        })],
      })),
    }));
  }
  return new Table({
    visuallyRightToLeft: true,
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: P.border },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: P.border },
      left: NB, right: NB,
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: P.inner },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: P.inner },
    },
    rows: trs,
  });
}

/* ---------- Arabic-aware cover title layout (R2, centered -- direction-safe) ---------- */
function splitTitleLinesAr(title, cpl) {
  if (title.length <= cpl) return [title];
  const words = title.split(" ");
  const lines = []; let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > cpl && cur) { lines.push(cur.trim()); cur = w; }
    else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur.trim());
  if (lines.length > 1 && lines[lines.length - 1].length <= 2) {
    const last = lines.pop(); lines[lines.length - 1] += " " + last;
  }
  return lines;
}
function calcTitleLayoutAr(title, maxWidthTwips, preferredPt = 36, minPt = 24) {
  const charW = (pt) => pt * 13; /* Arabic avg glyph width in twips */
  let titlePt = preferredPt, lines;
  while (titlePt >= minPt) {
    const cpl = Math.floor(maxWidthTwips / charW(titlePt));
    if (cpl < 4) { titlePt -= 2; continue; }
    lines = splitTitleLinesAr(title, cpl);
    if (lines.length <= 3) break;
    titlePt -= 2;
  }
  if (!lines || lines.length > 3) { lines = splitTitleLinesAr(title, Math.floor(maxWidthTwips / charW(minPt))); titlePt = minPt; }
  return { titlePt, titleLines: lines };
}
function calcCoverSpacing(prm) {
  const { titleLineCount = 1, titlePt = 36, hasSubtitle = false, hasEnglishLabel = false,
    metaLineCount = 0, fixedHeight = 800, pageHeight = 16838 } = prm;
  const SAFETY = 1200;
  const usable = pageHeight - SAFETY;
  const titleH = titleLineCount * (titlePt * 23 + 200);
  const subH = hasSubtitle ? (12 * 23 + 600) : 0;
  const engH = hasEnglishLabel ? (9 * 23 + 600) : 0;
  const metaH = metaLineCount * (10 * 23 + 100);
  const implicit = 3 * 300;
  const content = titleH + subH + engH + metaH + fixedHeight + implicit;
  const remaining = Math.max(usable - content, 400);
  const FOOTER_MIN = 800;
  const rawTop = Math.floor(remaining * 0.42);
  const rawBottom = Math.floor(remaining * 0.42);
  const bottomSpacing = Math.max(rawBottom, FOOTER_MIN);
  const topSpacing = Math.max(rawTop - Math.max(0, FOOTER_MIN - rawBottom), 400);
  return { topSpacing, bottomSpacing };
}

/* R2 cover -- Double-Rule Frame, centered (direction-neutral for Arabic) */
function buildCoverR2(config) {
  const pad = 1400;
  const { titlePt, titleLines } = calcTitleLayoutAr(config.title, 11906 - pad * 2, 36, 24);
  const titleSize = titlePt * 2;
  const spacing = calcCoverSpacing({
    titleLineCount: titleLines.length, titlePt,
    hasSubtitle: !!config.subtitle, hasEnglishLabel: !!config.englishLabel,
    metaLineCount: (config.metaLines || []).length, fixedHeight: 700,
  });
  const ch = [];
  ch.push(new Paragraph({ spacing: { before: spacing.topSpacing } }));
  ch.push(new Paragraph({
    indent: { left: pad, right: pad }, border: { bottom: { style: BorderStyle.SINGLE, size: 18, color: P.accent, space: 6 } },
    spacing: { after: 600 },
    children: [new TextRun({ text: "", size: 2 })],
  }));
  ch.push(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { after: 500 },
    children: [new TextRun({
      text: config.englishLabel.split("").join(" "), size: 18, color: P.accent,
      font: AR, characterSpacing: 40,
    })],
  }));
  for (let i = 0; i < titleLines.length; i++) {
    ch.push(new Paragraph({
      bidirectional: true, alignment: AlignmentType.CENTER,
      spacing: { after: i < titleLines.length - 1 ? 100 : 300, line: Math.ceil(titlePt * 23), lineRule: "atLeast" },
      children: [new TextRun({ text: titleLines[i], size: titleSize, sizeComplexScript: titleSize, bold: true, color: P.title, font: AR, rightToLeft: true })],
    }));
  }
  if (config.subtitle) {
    ch.push(new Paragraph({
      bidirectional: true, alignment: AlignmentType.CENTER, spacing: { after: 700, line: 340 },
      children: [new TextRun({ text: config.subtitle, size: 26, sizeComplexScript: 26, color: P.subtitle, font: AR, rightToLeft: true })],
    }));
  }
  for (const line of (config.metaLines || [])) {
    ch.push(new Paragraph({
      bidirectional: true, alignment: AlignmentType.CENTER, spacing: { after: 120, line: 460, lineRule: "atLeast" },
      children: mkRuns(line, { size: 30, color: P.meta }),
    }));
  }
  ch.push(new Paragraph({ spacing: { before: spacing.bottomSpacing } }));
  ch.push(new Paragraph({
    indent: { left: pad, right: pad }, border: { top: { style: BorderStyle.SINGLE, size: 18, color: P.accent, space: 6 } },
    spacing: { before: 200 },
    children: [
      new TextRun({ text: config.footerLeft, size: 16, color: P.footer, font: AR }),
      new TextRun({ text: "      ", size: 16 }),
      new TextRun({ text: config.footerRight, size: 16, color: P.footer, font: AR }),
    ],
  }));
  return [new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    layout: TableLayoutType.FIXED,
    borders: allNoBorders,
    rows: [new TableRow({
      height: { value: 16838, rule: "exact" },
      children: [new TableCell({ shading: { type: ShadingType.CLEAR, fill: P.bg }, borders: noBorders, children: ch })],
    })],
  })];
}

/* ---------- content walker ---------- */
function walk(blocks) {
  const out = [];
  for (const b of blocks) {
    if (b.t === "h1") out.push(h1(b.x));
    else if (b.t === "h2") out.push(h2(b.x));
    else if (b.t === "p") out.push(para(b.x));
    else if (b.t === "callout") out.push(callout(b.x));
    else if (b.t === "table") { if (b.caption) out.push(tableCaption(b.caption)); out.push(tableBlock(b.header, b.rows, b.widths)); out.push(new Paragraph({ spacing: { after: 120 }, children: [] })); }
    else if (b.t === "img") out.push(...imageBlock(b.src, b.w, b.caption));
  }
  return out;
}

/* ---------- assemble ---------- */
const c1 = require("./content1.js");
const c2 = require("./content2.js");
const c3 = require("./content3.js");
const bodyChildren = walk([...c1, ...c2, ...c3]);

const pgSize = { width: 11906, height: 16838 };
const pgMargin = { top: 1440, bottom: 1440, left: 1701, right: 1417 };

const runningHeader = new Header({
  children: [new Paragraph({
    bidirectional: true, alignment: AlignmentType.CENTER,
    border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: P.inner, space: 4 } },
    spacing: { after: 60 },
    children: [new TextRun({ text: "التدقيق الشامل لنظام الهندسة الوكيلي — AES-AUDIT-001", size: 18, color: "8A93A0", font: AR, rightToLeft: true })],
  })],
});
const pageFooter = () => new Footer({
  children: [new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, color: P.secondary, font: AR })],
  })],
});

const doc = new Document({
  styles: { default: { document: {
    run: { font: AR, size: 24, sizeComplexScript: 24, color: P.body },
    paragraph: { spacing: { line: 312 } },
  }}},
  sections: [
    { /* S1: cover -- margin 0, no footer */
      properties: { page: { size: pgSize, margin: { top: 0, bottom: 0, left: 0, right: 0 } } },
      children: buildCoverR2({
        title: "التدقيق الشامل لنظام الهندسة الوكيلي",
        subtitle: "الفحص المعماري والبصري والتشغيلي، النقد القاسي، والمقارنة مع DeepSeek Harness",
        englishLabel: "AES-AUDIT-001",
        metaLines: [
          "المرجع المقيَّم: الالتزام المنشور `0f2d9c6b` عبر الرابط العام",
          "جلسة أدلة مصرَّحة حية: 16 لقطة على `1440px` و`390px` بتاريخ 2026-10-26",
          "الدرجات الإجمالية: معماريًا `5/10` — بصريًا `4.5/10` — تشغيليًا `6/10`",
        ],
        footerLeft: "Agentic Engineering System", footerRight: "2026-10-26",
      }),
    },
    { /* S2: front matter -- TOC, roman */
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.UPPER_ROMAN } },
      },
      headers: { default: runningHeader },
      footers: { default: pageFooter() },
      children: [
        new Paragraph({
          bidirectional: true, alignment: AlignmentType.CENTER, spacing: { before: 480, after: 360 },
          children: [new TextRun({ text: "المحتويات", bold: true, size: 32, sizeComplexScript: 32, font: AR, rightToLeft: true, color: P.primary })],
        }),
        new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
        new Paragraph({
          bidirectional: true, spacing: { before: 200 },
          children: [new TextRun({
            text: "ملاحظة: جدول المحتويات مولَّد بحقول آلية — بعد أي تعديل انقر عليه بالزر الأيمن واختر «تحديث الحقل» لتحديث أرقام الصفحات.",
            size: 18, color: "888888", font: AR, rightToLeft: true, italics: true,
          })],
        }),
        /* no trailing PageBreak: body section is SectionType.NEXT_PAGE (double break = blank page) */
      ],
    },
    { /* S3: body -- arabic numerals from 1 */
      properties: {
        type: SectionType.NEXT_PAGE,
        page: { size: pgSize, margin: pgMargin, pageNumbers: { start: 1, formatType: NumberFormat.DECIMAL } },
      },
      headers: { default: runningHeader },
      footers: { default: pageFooter() },
      children: bodyChildren,
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("WROTE", OUT, buf.length, "bytes");
});
