/**
 * The sweep dataset browsing tab.
 *
 * Every row was measured against the prices the dataset carries in its own
 * meta, not against whatever the price page currently holds. When the two
 * disagree the page says so: reading these figures as if they used today's
 * prices is the easiest way to draw a wrong conclusion from them.
 */

import * as store from "./prices-store.js";
import { formatYi } from "./format.js";

const POLICY_LABEL = { full: "完整修復", to_12: "修復至 12 星" };

let datasets = null;
let sort = { key: "total_cost_mean", direction: 1 };

const el = {};

function bind() {
  for (const id of [
    "data-source", "data-equipment", "data-target", "data-start", "data-policy",
    "data-meta", "data-price-warning", "data-count",
  ]) {
    el[id] = document.getElementById(id);
  }
  el.table = document.getElementById("data-table");
  el.body = el.table.querySelector("tbody");
}

function active() {
  return datasets[el["data-source"].value];
}

function distinct(rows, key) {
  return [...new Set(rows.map((row) => row[key]))].sort((a, b) =>
    typeof a === "number" ? a - b : String(a).localeCompare(String(b))
  );
}

function fillFilter(select, values, label = (v) => v) {
  const chosen = select.value;
  select.innerHTML =
    `<option value="">全部</option>` +
    values.map((value) => `<option value="${value}">${label(value)}</option>`).join("");
  if (values.map(String).includes(chosen)) {
    select.value = chosen;
  }
}

function fillFilters() {
  const dataset = active();
  if (!dataset) return;
  const rows = dataset.results;
  fillFilter(el["data-equipment"], distinct(rows, "equipment"));
  fillFilter(el["data-target"], distinct(rows, "target_star"), (v) => `${v} 星`);
  fillFilter(el["data-start"], distinct(rows, "start_star"), (v) => `${v} 星`);
}

/** Which of the dataset's prices no longer match what the browser is using. */
function priceDrift(dataset) {
  const snapshot = dataset.meta.prices;
  const current = store.currentPrices();
  const changed = [];

  for (const [star, price] of Object.entries(snapshot.star_scroll_cost)) {
    if (current.star_scroll_cost[star] !== price) {
      changed.push(`${star} 星星捲`);
    }
  }
  for (const item of snapshot.equipment) {
    const now = current.equipment.find((entry) => entry.name === item.name);
    if (!now || now.price !== item.price) {
      changed.push(item.name);
    }
  }
  return changed;
}

function sortValue(row, key) {
  if (key.startsWith("p")) {
    return row.total_cost_percentiles[key.slice(1)];
  }
  return row[key];
}

function renderMeta() {
  const dataset = active();
  if (!dataset) {
    el["data-meta"].textContent = "這個資料集還沒產生，請先跑 sweep.py 再跑 build_site_data.py。";
    el["data-price-warning"].hidden = true;
    return;
  }

  const meta = dataset.meta;
  const pending = (meta.target_stars || []).filter(
    (star) => !(meta.targets_completed || []).includes(star)
  );
  el["data-meta"].textContent =
    `產生於 ${meta.generated_at}　每組 ${meta.trials.toLocaleString("en-US")} 次　種子 ${meta.seed}` +
    `　已完成目標 ${(meta.targets_completed || []).join("、")} 星` +
    (pending.length ? `　（${pending.join("、")} 星尚未跑完）` : "");

  const changed = priceDrift(dataset);
  el["data-price-warning"].hidden = changed.length === 0;
  if (changed.length) {
    el["data-price-warning"].textContent =
      `注意：這些結果是用資料集內建的價格快照算出來的，而以下項目現在的價格已經不同 - ` +
      `${changed.join("、")}。要讓數字跟上，請改完價格後重跑 sweep.py 與 build_site_data.py。`;
  }
}

function render() {
  renderMeta();
  const dataset = active();
  if (!dataset) {
    el.body.innerHTML = "";
    el["data-count"].textContent = "";
    return;
  }

  const equipment = el["data-equipment"].value;
  const target = el["data-target"].value;
  const start = el["data-start"].value;
  const policy = el["data-policy"].value;

  const rows = dataset.results
    .filter((row) => equipment === "" || row.equipment === equipment)
    .filter((row) => target === "" || String(row.target_star) === target)
    .filter((row) => start === "" || String(row.start_star) === start)
    .filter((row) => policy === "" || row.repair_policy === policy)
    .sort((a, b) => {
      const left = sortValue(a, sort.key);
      const right = sortValue(b, sort.key);
      if (typeof left === "string") {
        return left.localeCompare(right) * sort.direction;
      }
      return (left - right) * sort.direction;
    });

  el.body.innerHTML = rows
    .map(
      (row) => `<tr>
        <td>${row.equipment}</td>
        <td class="num">${row.level}</td>
        <td class="num">${row.start_star}</td>
        <td class="num">${row.target_star}</td>
        <td>${POLICY_LABEL[row.repair_policy]}</td>
        <td class="num strong">${formatYi(row.total_cost_mean)}</td>
        <td class="num">${formatYi(row.total_cost_percentiles["50"])}</td>
        <td class="num">${formatYi(row.total_cost_percentiles["75"])}</td>
        <td class="num">${formatYi(row.total_cost_percentiles["90"])}</td>
        <td class="num">${formatYi(row.total_cost_percentiles["95"])}</td>
        <td class="num">${formatYi(row.meso_mean)}</td>
        <td class="num">${formatYi(row.equipment_cost_mean)}</td>
        <td class="num">${row.destroys_mean.toFixed(2)}</td>
        <td class="num">${row.attempts_mean.toFixed(1)}</td>
      </tr>`
    )
    .join("");

  el["data-count"].textContent = `${rows.length} / ${dataset.results.length} 組合`;
}

export function initData(loadedDatasets) {
  datasets = loadedDatasets;
  bind();
  fillFilters();

  el["data-source"].addEventListener("change", () => {
    fillFilters();
    render();
  });
  for (const id of ["data-equipment", "data-target", "data-start", "data-policy"]) {
    el[id].addEventListener("change", render);
  }

  el.table.querySelectorAll("th[data-sort]").forEach((header) => {
    header.addEventListener("click", () => {
      const key = header.dataset.sort;
      sort = { key, direction: sort.key === key ? -sort.direction : 1 };
      el.table.querySelectorAll("th").forEach((th) => th.classList.remove("asc", "desc"));
      header.classList.add(sort.direction === 1 ? "asc" : "desc");
      render();
    });
  });

  store.onChange(render);
  render();
}
