// A small, safe Markdown renderer for the agent's ADR, specs and notes (ported from deployment/ui/markdown.js). React
// elements only, no HTML injection, so model output can never add markup. Supports # headings, paragraphs, - / * / 1.
// lists, | tables |, ``` code fences, > quotes, **bold**, *italic* and `code`.

function inline(text, keyBase) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${m.index}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isRule = (line) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);
const isTable = (lines, i) => lines[i].trim().startsWith("|") && i + 1 < lines.length && isRule(lines[i + 1]);
const LIST = /^\s*([-*]|\d+\.)\s+/;

function blocks(md, label) {
  const lines = String(md || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  let tables = 0;
  while (i < lines.length) {
    const line = lines[i];
    const k = `b${i}`;
    if (!line.trim()) { i += 1; continue; }
    if (line.startsWith("```")) {
      const buf = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) { buf.push(lines[i]); i += 1; }
      i += 1;
      out.push(<pre key={k}>{buf.join("\n")}</pre>);
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const Tag = `h${Math.min(6, h[1].length + 1)}`;
      out.push(<Tag key={k}>{inline(h[2], k)}</Tag>);
      i += 1;
      continue;
    }
    if (isTable(lines, i)) {
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) { rows.push(cells(lines[i])); i += 1; }
      tables += 1;
      out.push(
        <div key={k} className="md-table" tabIndex={0} role="region" aria-label={`${label} table ${tables}`}>
          <table>
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (LIST.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && LIST.test(lines[i])) { items.push(lines[i].replace(LIST, "")); i += 1; }
      const Tag = ordered ? "ol" : "ul";
      out.push(<Tag key={k}>{items.map((t, j) => <li key={j}>{inline(t, `${k}i${j}`)}</li>)}</Tag>);
      continue;
    }
    if (line.startsWith(">")) {
      const buf = [];
      while (i < lines.length && lines[i].startsWith(">")) { buf.push(lines[i].replace(/^>\s?/, "")); i += 1; }
      out.push(<blockquote key={k}>{inline(buf.join(" "), k)}</blockquote>);
      continue;
    }
    const buf = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|\s*([-*]|\d+\.)\s+)/.test(lines[i]) && !isTable(lines, i)) {
      buf.push(lines[i].trim());
      i += 1;
    }
    if (!buf.length) { buf.push(line.trim()); i += 1; }   // never stall on an odd line
    out.push(<p key={k}>{inline(buf.join(" "), k)}</p>);
  }
  return out;
}

// `label` names the document, so each scrolling table is its own named region ("Decision record table 2").
export default function Markdown({ text, label = "Document", className = "" }) {
  return <div className={`md ${className}`.trim()}>{blocks(text, label)}</div>;
}
