/**
 * The hand-driven simulation tab.
 *
 * The buttons mirror the Session rules rather than duplicating them: a scroll
 * that cannot raise the item never appears in the dropdown, repair only lights
 * up on a destroyed item, and enhancing stops at the level cap. Anything that
 * still slips through surfaces as the engine's own error message.
 */

import * as rules from "./rules.js";
import * as store from "./prices-store.js";
import { Session, RepairPolicy } from "./session.js";
import { runWithinBudget, runToStar, autoPolicy, StopReason } from "./autorun.js";
import { formatMeso, parseMeso, parseStar } from "./format.js";

const ACTION_LABEL = {
  enhance: "強化",
  scroll: "星捲",
  repair_full: "完整修復",
  repair_to_12: "修復至 12 星",
};

const OUTCOME_LABEL = {
  success: "成功",
  maintain: "維持",
  destroy: "破壞",
};

let datasets = null;
let session = null;

const el = {};

function bind() {
  for (const id of [
    "play-equipment", "play-level", "play-level-field", "play-start-star",
    "play-new", "play-star", "play-total", "play-subtotal", "play-flag",
    "play-enhance", "play-scroll-star", "play-scroll", "play-repair-full",
    "play-repair-12", "play-error", "play-copy", "play-summary",
    "auto-repair", "auto-scroll", "auto-budget", "auto-budget-target",
    "auto-budget-run", "auto-star-target", "auto-star-budget", "auto-star-run",
    "auto-star-hint", "auto-result",
  ]) {
    el[id] = document.getElementById(id);
  }
  el.logBody = document.querySelector("#play-log tbody");
}

function fillSetup() {
  const prices = store.currentPrices();
  const chosen = el["play-equipment"].value;
  el["play-equipment"].innerHTML =
    `<option value="">不指定（修復裝備計 0）</option>` +
    prices.equipment
      .map(
        (item) =>
          `<option value="${item.name}">${item.name}（Lv${item.level}・${formatMeso(item.price)}）</option>`
      )
      .join("");
  el["play-equipment"].value = chosen;
  if (el["play-equipment"].value === "" && chosen !== "") {
    // The equipment this session used has been removed from the price table.
    el["play-equipment"].value = "";
  }

  el["play-level"].innerHTML = rules
    .supportedLevels()
    .map((level) => `<option value="${level}">${level}</option>`)
    .join("");
  el["play-level"].value = String(rules.supportedLevels()[2]);

  el["auto-scroll"].innerHTML =
    `<option value="">不使用</option>` +
    rules
      .starScrollStars()
      .map((star) => `<option value="${star}">${star} 星星捲</option>`)
      .join("");

  syncLevelField();
}

function syncLevelField() {
  const usingCatalogue = el["play-equipment"].value !== "";
  el["play-level-field"].hidden = usingCatalogue;
}

function chosenLevel() {
  const name = el["play-equipment"].value;
  if (name === "") {
    return Number(el["play-level"].value);
  }
  return store.lookup(name).level;
}

function showError(message) {
  el["play-error"].hidden = message === null;
  el["play-error"].textContent = message || "";
}

function newSession() {
  showError(null);
  el["auto-result"].hidden = true;
  try {
    const name = el["play-equipment"].value;
    const item = name === "" ? null : store.lookup(name);
    session = new Session({
      level: item === null ? Number(el["play-level"].value) : item.level,
      startStar: Number(el["play-start-star"].value),
      equipmentName: item === null ? null : item.name,
      equipmentPrice: item === null ? 0 : item.price,
    });
  } catch (error) {
    session = null;
    showError(error.message);
  }
  render();
}

function act(fn) {
  showError(null);
  try {
    fn();
  } catch (error) {
    showError(error.message);
  }
  render();
}

function currentPolicy() {
  const scroll = el["auto-scroll"].value;
  return autoPolicy({
    repairPolicy: el["auto-repair"].value,
    scrollStar: scroll === "" ? null : Number(scroll),
  });
}

function reportAuto(result) {
  const box = el["auto-result"];
  box.hidden = false;
  box.className = "banner";
  if (result.stop_reason === StopReason.REACHED_TARGET) {
    box.textContent = `達標：${result.star} 星，本次花費 ${formatMeso(result.spent)}`;
  } else if (result.destroyed) {
    box.className = "banner bad";
    box.textContent =
      `預算用盡，而且 ${result.star} 星痕跡還沒修復 - 剩下的錢付不起任何一種修復。` +
      `本次花費 ${formatMeso(result.spent)}`;
  } else {
    box.className = "banner warn";
    box.textContent = `預算用盡，停在 ${result.star} 星，本次花費 ${formatMeso(result.spent)}`;
  }
}

function runBudget() {
  act(() => {
    if (session === null) throw new Error("請先建立裝備");
    const budget = parseMeso(el["auto-budget"].value);
    const target = parseStar(el["auto-budget-target"].value);
    reportAuto(runWithinBudget(session, target, budget, currentPolicy()));
  });
}

function runTarget() {
  act(() => {
    if (session === null) throw new Error("請先建立裝備");
    const target = parseStar(el["auto-star-target"].value);
    const raw = el["auto-star-budget"].value.trim();
    if (raw === "") {
      throw new Error("請填保險絲預算：沒有上限的話，跑不完的組合會讓瀏覽器停不下來");
    }
    reportAuto(runToStar(session, target, parseMeso(raw), currentPolicy()));
  });
}

/**
 * The p95 total cost of the cheapest measured route to this target, used as the
 * default fuse. It is a measured figure, not a guess - and it is only a rough
 * fit, because the dataset's rows start from their own stars, not from wherever
 * this session happens to be.
 */
function suggestBudget() {
  const name = el["play-equipment"].value;
  const hint = el["auto-star-hint"];
  let target;
  try {
    target = parseStar(el["auto-star-target"].value);
  } catch (error) {
    hint.textContent = error.message;
    return;
  }

  if (name === "" || datasets === null) {
    hint.textContent = "選擇資料集內的裝備後，這裡會帶出建議的保險絲預算。";
    return;
  }

  let best = null;
  for (const dataset of [datasets.simulations, datasets.marginal]) {
    if (!dataset) continue;
    for (const row of dataset.results) {
      if (row.equipment !== name || row.target_star !== target) continue;
      if (best === null || row.total_cost_mean < best.total_cost_mean) best = row;
    }
  }

  if (best === null) {
    hint.textContent = `資料集裡沒有「${name}」到 ${target} 星的結果，請自行填一個上限。`;
    return;
  }

  const p95 = best.total_cost_percentiles["95"];
  if (el["auto-star-budget"].value.trim() === "") {
    el["auto-star-budget"].value = `${(p95 / 100000000).toFixed(1)}e`;
  }
  hint.textContent =
    `建議上限 ${formatMeso(p95)}：資料集中「${name}」到 ${target} 星最便宜路線` +
    `（${best.start_star} 星起手、${best.repair_policy === "full" ? "完整修復" : "修復至 12 星"}）的 p95。`;
}

function renderLog() {
  const rows = session === null ? [] : session.log;
  el.logBody.innerHTML = rows
    .map((entry) => {
      const outcome = entry.outcome === null ? "" : OUTCOME_LABEL[entry.outcome];
      const cost = entry.meso + entry.equipment_cost;
      return `<tr class="${entry.outcome === "destroy" ? "destroy" : ""}">
        <td class="num">${entry.index}</td>
        <td>${ACTION_LABEL[entry.action]}</td>
        <td>${entry.star_before} → ${entry.star_after}</td>
        <td>${outcome}</td>
        <td class="num">${formatMeso(cost)}</td>
        <td class="num">${formatMeso(entry.total_cost_after)}</td>
      </tr>`;
    })
    .join("");

  if (session === null || rows.length === 0) {
    el["play-summary"].textContent = "尚未有任何操作。";
    return;
  }
  const t = session.totals;
  el["play-summary"].textContent =
    `楓幣 ${formatMeso(t.total_meso)}　裝備成本 ${formatMeso(t.equipment_cost)}（${t.equipment_used} 件）` +
    `　總計 ${formatMeso(session.totalCost)}　星捲 ${t.scrolls_used}　強化 ${t.attempts} 次　破壞 ${t.destroys} 次`;
}

function render() {
  const live = session !== null;
  el["play-star"].textContent = live ? session.star : "-";
  el["play-total"].textContent = live ? formatMeso(session.totalCost) : "0.00億";
  el["play-subtotal"].textContent = live
    ? `等級 ${session.level}・${session.equipmentName || "未指定裝備"}・上限 ${session.maxStar} 星`
    : "";

  el["play-flag"].hidden = !(live && session.destroyed);
  if (live && session.destroyed) {
    el["play-flag"].textContent = `裝備已破壞，留下 ${session.star} 星痕跡 - 先修復才能繼續。`;
  }

  el["play-enhance"].disabled = !live || !session.canEnhance;
  el["play-repair-full"].disabled = !live || !session.destroyed;
  el["play-repair-12"].disabled = !live || !session.destroyed;

  const scrolls = live ? session.availableScrolls() : [];
  const chosen = el["play-scroll-star"].value;
  el["play-scroll-star"].innerHTML = scrolls
    .map((star) => `<option value="${star}">${star} 星星捲　${formatMeso(rules.starScrollCost(star))}</option>`)
    .join("");
  if (scrolls.includes(Number(chosen))) {
    el["play-scroll-star"].value = chosen;
  }
  el["play-scroll-star"].disabled = scrolls.length === 0;
  el["play-scroll"].disabled = scrolls.length === 0;

  renderLog();
  suggestBudget();
}

function copyLog() {
  if (session === null || session.log.length === 0) return;
  const lines = session.log.map((entry) => {
    const outcome = entry.outcome === null ? "" : OUTCOME_LABEL[entry.outcome];
    const cost = entry.meso + entry.equipment_cost;
    return [
      String(entry.index).padStart(3),
      ACTION_LABEL[entry.action],
      `${entry.star_before} -> ${entry.star_after}`,
      outcome,
      formatMeso(cost),
      formatMeso(entry.total_cost_after),
    ].join("\t");
  });
  lines.push(el["play-summary"].textContent);
  navigator.clipboard.writeText(lines.join("\n")).then(
    () => { el["play-copy"].textContent = "已複製"; setTimeout(() => { el["play-copy"].textContent = "複製"; }, 1500); },
    (error) => showError(`複製失敗：${error.message}`)
  );
}

export function initPlay(loadedDatasets) {
  datasets = loadedDatasets;
  bind();
  fillSetup();

  el["play-equipment"].addEventListener("change", () => { syncLevelField(); suggestBudget(); });
  el["play-level"].addEventListener("change", () => {
    el["play-start-star"].max = String(rules.maxTargetStar(chosenLevel()));
  });
  el["play-new"].addEventListener("click", newSession);
  el["play-enhance"].addEventListener("click", () => act(() => session.enhance()));
  el["play-scroll"].addEventListener("click", () =>
    act(() => session.useScroll(Number(el["play-scroll-star"].value)))
  );
  el["play-repair-full"].addEventListener("click", () =>
    act(() => session.repair(RepairPolicy.FULL))
  );
  el["play-repair-12"].addEventListener("click", () =>
    act(() => session.repair(RepairPolicy.TO_12))
  );
  el["auto-budget-run"].addEventListener("click", runBudget);
  el["auto-star-run"].addEventListener("click", runTarget);
  el["auto-star-target"].addEventListener("change", suggestBudget);
  el["play-copy"].addEventListener("click", copyLog);

  store.onChange(() => {
    fillSetup();
    render();
  });

  newSession();
}
