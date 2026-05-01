"use strict";

const data = JSON.parse(document.getElementById("app-data").textContent);

function escape(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const cellMap = new Map();
for (const c of data.cells) cellMap.set(c.model + "::" + c.test, c);

function cellColor(k, n) {
  const ratio = k / n;
  return `hsl(${Math.round(120 * ratio)}, 60%, 78%)`;
}

const CLIFF_THRESHOLD = 0.7;

function findCliffIndex(modelId, allTests) {
  let lastPassIdx = -1;
  allTests.forEach((t, idx) => {
    const cell = cellMap.get(modelId + "::" + t.id);
    if (cell && cell.n > 0 && cell.k / cell.n >= CLIFF_THRESHOLD) lastPassIdx = idx;
  });
  return lastPassIdx;
}

function renderHeader() {
  const classKeys = Object.keys(data.tests);
  const classRow = ["<th></th>"];
  for (const cls of classKeys) {
    const span = data.tests[cls].length;
    classRow.push(`<th class="class-band" colspan="${span}">${escape(cls)} — ${escape(data.class_labels[cls] || "")}</th>`);
  }
  const testRow = ["<th></th>"];
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      testRow.push(`<th class="test-label${sep}" title="${escape(t.desc || "")}">${escape(t.label)}</th>`);
    });
  });
  return `<thead><tr>${classRow.join("")}</tr><tr>${testRow.join("")}</tr></thead>`;
}

function renderRow(model) {
  const tds = [
    `<th class="row-label">${escape(model.label)}<span class="params">${escape(model.params)}</span></th>`,
  ];
  const classKeys = Object.keys(data.tests);
  const flatTests = classKeys.flatMap(cls => data.tests[cls]);
  const cliffIdx = findCliffIndex(model.id, flatTests);
  let absIdx = -1;
  classKeys.forEach((cls, i) => {
    data.tests[cls].forEach((t, j) => {
      absIdx += 1;
      const sep = (j === 0 && i > 0) ? " band-sep" : "";
      const cliff = absIdx === cliffIdx ? " cliff-edge" : "";
      const cell = cellMap.get(model.id + "::" + t.id);
      if (!cell) {
        tds.push(`<td class="empty${sep}${cliff}">—</td>`);
      } else {
        const bg = cellColor(cell.k, cell.n);
        tds.push(
          `<td class="cell${sep}${cliff}" style="background:${bg}" data-model="${escape(model.id)}" data-test="${escape(t.id)}">` +
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
    ([k, v]) => `<span><b>${escape(k)}:</b> ${escape(v)}</span>`
  ).join("");
  return `
    <header class="intro">
      <h1>Findings — local GUI grounding agents</h1>
      <div class="built">Built ${escape(data.built_at)}</div>
      <p>${escape(data.intro)}</p>
      <div class="legend">
        ${legendBits}
        <span><b>Cells:</b> k/n pass count · green = pass, red = fail, gray = not run.</span>
      </div>
    </header>`;
}

document.getElementById("app").innerHTML = renderIntro() + renderMatrix();

const panel = document.getElementById("panel");
const lightbox = document.getElementById("lightbox");

function openPanel(modelId, testId) {
  const model = data.models.find(m => m.id === modelId);
  const test = Object.values(data.tests).flat().find(t => t.id === testId);
  const cell = cellMap.get(modelId + "::" + testId);
  if (!cell) return;
  const runs = cell.runs.map(r => {
    const passClass = r.category === "pass" ? "pass" : "fail";
    const passLabel = r.category || r.outcome || "?";
    const ts = (r.ts || "").replace("T", " ").slice(0, 16);
    const steps = r.steps != null ? `${r.steps} steps` : "";
    const elapsed = r.elapsed_s != null ? `${r.elapsed_s.toFixed(1)}s` : "";
    const thumb = r.screenshot
      ? `<img class="thumb" src="${escape(r.screenshot)}" data-full="${escape(r.screenshot)}" alt="final screenshot">`
      : `<div class="meta">(no screenshot available)</div>`;
    return `
      <div class="run">
        <div class="meta">
          <span class="${passClass}">${escape(passLabel)}</span>
          <span>${escape(ts)}</span>
          <span>${escape(steps)}</span>
          <span>${escape(elapsed)}</span>
          <span>${escape(r.harness || "")}</span>
        </div>
        ${thumb}
      </div>`;
  }).join("");
  panel.innerHTML = `
    <button class="close" aria-label="Close">×</button>
    <h2>${escape(model.label)} × ${escape(test.label)}</h2>
    <div class="agg">${cell.k}/${cell.n} pass · n=${cell.n}</div>
    ${runs}`;
  panel.hidden = false;
}

function closePanel() { panel.hidden = true; }
function openLightbox(src) {
  lightbox.innerHTML = `<img src="${escape(src)}" alt="full screenshot">`;
  lightbox.hidden = false;
}
function closeLightbox() { lightbox.hidden = true; lightbox.innerHTML = ""; }

document.addEventListener("click", (e) => {
  const cellEl = e.target.closest("td.cell");
  if (cellEl) {
    openPanel(cellEl.dataset.model, cellEl.dataset.test);
    return;
  }
  if (e.target.matches("aside#panel button.close")) {
    closePanel();
    return;
  }
  if (e.target.matches("aside#panel img.thumb")) {
    openLightbox(e.target.dataset.full);
    return;
  }
  if (e.target.closest("#lightbox")) {
    closeLightbox();
    return;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!lightbox.hidden) closeLightbox();
  else if (!panel.hidden) closePanel();
});
