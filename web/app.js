"use strict";

const data = JSON.parse(document.getElementById("app-data").textContent);

const cellMap = new Map();
for (const c of data.cells) cellMap.set(c.model + "::" + c.test, c);

function cellColor(k, n) {
  if (n === 0) return "var(--gray-cell)";
  const ratio = k / n;
  return `hsl(${Math.round(120 * ratio)}, 60%, 78%)`;
}

function renderHeader() {
  const classKeys = Object.keys(data.tests);
  const classRow = ["<th></th>"];
  for (const cls of classKeys) {
    const span = data.tests[cls].length;
    classRow.push(`<th class="class-band" colspan="${span}">${cls} — ${data.class_labels[cls] || ""}</th>`);
  }
  const testRow = ["<th></th>"];
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      testRow.push(`<th class="test-label${sep}" title="${t.desc || ""}">${t.label}</th>`);
    });
  });
  return `<thead><tr>${classRow.join("")}</tr><tr>${testRow.join("")}</tr></thead>`;
}

function renderRow(model) {
  const tds = [
    `<th class="row-label">${model.label}<span class="params">${model.params}</span></th>`,
  ];
  const classKeys = Object.keys(data.tests);
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      const cell = cellMap.get(model.id + "::" + t.id);
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      if (!cell) {
        tds.push(`<td class="empty${sep}">—</td>`);
      } else {
        const bg = cellColor(cell.k, cell.n);
        tds.push(
          `<td class="cell${sep}" style="background:${bg}" data-model="${model.id}" data-test="${t.id}">` +
          `${cell.k}/${cell.n}<span class="n">·n=${cell.n}</span></td>`
        );
      }
    });
  });
  return `<tr>${tds.join("")}</tr>`;
}

function renderMatrix() {
  const rows = data.models.map(renderRow).join("");
  return `<table class="matrix">${renderHeader()}<tbody>${rows}</tbody></table>`;
}

function renderIntro() {
  const legendBits = Object.entries(data.class_labels).map(
    ([k, v]) => `<span><b>${k}:</b> ${v}</span>`
  ).join("");
  return `
    <header class="intro">
      <h1>Findings — local GUI grounding agents</h1>
      <div class="built">Built ${data.built_at}</div>
      <p>${data.intro}</p>
      <div class="legend">
        ${legendBits}
        <span><b>Cells:</b> k/n pass count · green = pass, red = fail, gray = not run.</span>
      </div>
    </header>`;
}

document.getElementById("app").innerHTML = renderIntro() + renderMatrix();
