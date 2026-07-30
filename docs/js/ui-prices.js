/**
 * The price tab: edit what the market currently charges.
 *
 * Saving writes to localStorage and re-prices the simulation immediately. It
 * cannot write back to the repo, so the export button produces the exact shape
 * data/volatile.json expects, for the operator to paste in and re-run sweep.py.
 *
 * Validation matches starforce/volatile_data.py: every scroll star present,
 * prices non-negative integers, levels from the published list, and names that
 * stay distinct after the same normalisation the Python loader applies.
 */

import * as rules from "./rules.js";
import * as store from "./prices-store.js";
import { YI } from "./format.js";

const COMMENT =
  "浮動資料：會隨市場變動的價格。單位為楓幣，1e = 100000000。" +
  "固定資料（強化機率、強化費用、修復楓幣、修復裝備數量）在 starforce/static_data.py。";

const BREAKTHROUGH_COMMENT =
  "突破星捲價格。key 為「上限星數-成功率萬分點」，例如 23-3000 就是突破23星30%。" +
  "哪些捲存在寫在 starforce/static_data.py 的 BREAKTHROUGH_SCROLLS。";

let draft = null;
const el = {};

function bind() {
  for (const id of [
    "prices-save", "prices-reset", "prices-export", "prices-status",
    "prices-add", "prices-export-card", "prices-json",
  ]) {
    el[id] = document.getElementById(id);
  }
  el.scrolls = document.querySelector("#prices-scrolls tbody");
  el.breakthrough = document.querySelector("#prices-breakthrough tbody");
  el.equipment = document.querySelector("#prices-equipment tbody");
}

function toYiInput(meso) {
  return String(meso / YI);
}

function loadDraft() {
  draft = JSON.parse(JSON.stringify(store.currentPrices()));
}

function renderScrolls() {
  el.scrolls.innerHTML = rules
    .starScrollStars()
    .map(
      (star) => `<tr>
        <td>${star} 星</td>
        <td class="num">
          <input type="number" step="any" min="0" data-star="${star}"
                 value="${toYiInput(draft.star_scroll_cost[String(star)])}">
        </td>
      </tr>`
    )
    .join("");

  el.scrolls.querySelectorAll("input[data-star]").forEach((input) => {
    input.addEventListener("input", () => {
      draft.star_scroll_cost[input.dataset.star] = Math.round(
        Number(input.value) * YI
      );
      markDirty();
    });
  });
}

/** One row per breakthrough scroll. Which ones exist is fixed, only prices move. */
function renderBreakthrough() {
  el.breakthrough.innerHTML = rules
    .breakthroughScrolls()
    .map(([capStar, success]) => {
      const id = rules.breakthroughId(capStar, success);
      return `<tr>
        <td>${rules.breakthroughLabel(capStar, success)}</td>
        <td class="num">
          <input type="number" step="any" min="0" data-breakthrough="${id}"
                 value="${toYiInput(draft.breakthrough_scroll_cost[id])}">
        </td>
      </tr>`;
    })
    .join("");

  el.breakthrough.querySelectorAll("input[data-breakthrough]").forEach((input) => {
    input.addEventListener("input", () => {
      draft.breakthrough_scroll_cost[input.dataset.breakthrough] = Math.round(
        Number(input.value) * YI
      );
      markDirty();
    });
  });
}

function renderEquipment() {
  const levels = rules.supportedLevels();
  el.equipment.innerHTML = draft.equipment
    .map(
      (item, index) => `<tr>
        <td><input data-field="name" data-index="${index}" value="${item.name}"></td>
        <td>
          <select data-field="level" data-index="${index}">
            ${levels
              .map(
                (level) =>
                  `<option value="${level}"${level === item.level ? " selected" : ""}>${level}</option>`
              )
              .join("")}
          </select>
        </td>
        <td class="num">
          <input type="number" step="any" min="0" data-field="price" data-index="${index}"
                 value="${toYiInput(item.price)}">
        </td>
        <td><button class="link" data-remove="${index}">刪除</button></td>
      </tr>`
    )
    .join("");

  el.equipment.querySelectorAll("[data-field]").forEach((input) => {
    input.addEventListener("input", () => {
      const item = draft.equipment[Number(input.dataset.index)];
      if (input.dataset.field === "name") {
        item.name = input.value;
      } else if (input.dataset.field === "level") {
        item.level = Number(input.value);
      } else {
        item.price = Math.round(Number(input.value) * YI);
      }
      markDirty();
    });
  });

  el.equipment.querySelectorAll("[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      draft.equipment.splice(Number(button.dataset.remove), 1);
      renderEquipment();
      markDirty();
    });
  });
}

function markDirty() {
  el["prices-status"].textContent = "尚未儲存";
  el["prices-status"].className = "muted warn-text";
}

/** Returns an error message, or null when the draft is safe to save. */
function validate() {
  for (const star of rules.starScrollStars()) {
    const price = draft.star_scroll_cost[String(star)];
    if (!Number.isInteger(price) || price < 0) {
      return `${star} 星星捲的價格不是有效數字`;
    }
  }

  for (const [capStar, success] of rules.breakthroughScrolls()) {
    const price = draft.breakthrough_scroll_cost[rules.breakthroughId(capStar, success)];
    if (!Number.isInteger(price) || price < 0) {
      return `${rules.breakthroughLabel(capStar, success)}的價格不是有效數字`;
    }
  }

  if (draft.equipment.length === 0) {
    return "至少要留一件裝備";
  }

  const seen = new Map();
  for (const item of draft.equipment) {
    if (!item.name.trim()) {
      return "裝備名稱不可空白";
    }
    if (!rules.supportedLevels().includes(item.level)) {
      return `「${item.name}」的等級 ${item.level} 不在官方公布的等級內`;
    }
    if (!Number.isInteger(item.price) || item.price < 0) {
      return `「${item.name}」的價格不是有效數字`;
    }
    const key = store.normalizeName(item.name);
    if (seen.has(key)) {
      return `「${item.name}」與「${seen.get(key)}」正規化後同名，Python 端會拒絕載入`;
    }
    seen.set(key, item.name);
  }
  return null;
}

function save() {
  const problem = validate();
  if (problem !== null) {
    el["prices-status"].textContent = problem;
    el["prices-status"].className = "muted bad-text";
    return;
  }
  store.save(draft);
  el["prices-status"].textContent = "已儲存到這個瀏覽器";
  el["prices-status"].className = "muted ok-text";
}

function reset() {
  store.reset();
  loadDraft();
  renderScrolls();
  renderBreakthrough();
  renderEquipment();
  el["prices-status"].textContent = "已還原成內建價格";
  el["prices-status"].className = "muted ok-text";
}

function exportJson() {
  const problem = validate();
  if (problem !== null) {
    el["prices-status"].textContent = problem;
    el["prices-status"].className = "muted bad-text";
    return;
  }
  const payload = {
    _comment: COMMENT,
    star_scroll_cost: draft.star_scroll_cost,
    _breakthrough_comment: BREAKTHROUGH_COMMENT,
    breakthrough_scroll_cost: draft.breakthrough_scroll_cost,
    equipment: draft.equipment.map((item) => ({
      name: item.name,
      level: item.level,
      price: item.price,
      aliases: item.aliases || [],
    })),
  };
  el["prices-json"].value = JSON.stringify(payload, null, 2);
  el["prices-export-card"].hidden = false;
  el["prices-json"].select();
}

export function initPrices() {
  bind();
  loadDraft();
  renderScrolls();
  renderBreakthrough();
  renderEquipment();

  el["prices-save"].addEventListener("click", save);
  el["prices-reset"].addEventListener("click", reset);
  el["prices-export"].addEventListener("click", exportJson);
  el["prices-add"].addEventListener("click", () => {
    draft.equipment.push({
      name: "新裝備",
      level: rules.supportedLevels()[2],
      price: 0,
      aliases: [],
    });
    renderEquipment();
    markDirty();
  });

  el["prices-status"].textContent = store.isModified()
    ? "目前使用的是這個瀏覽器儲存的價格"
    : "目前使用內建價格";
}
