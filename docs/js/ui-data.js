/**
 * The sweep dataset browsing tab.
 *
 * Every row was measured against the prices the dataset carries in its own
 * meta, not against whatever the price page currently holds. When the two
 * disagree the page says so: reading these figures as if they used today's
 * prices is the easiest way to draw a wrong conclusion from them.
 */

import * as store from "./prices-store.js";
import { rebuildBasis, repricedMean } from "./reprice.js";
import { describe, describeCompact } from "./policy.js";
import { formatYi } from "./format.js";

const POLICY_LABEL = { full: "完整修復", to_12: "修復至 12 星" };

const BREAKTHROUGH_LABEL = {
  none: "不用突破捲",
  optimal: "最省平均",
  safe: "只用必中",
};

let datasets = null;
let sort = { key: "repriced_mean", direction: 1 };

const el = {};

function bind() {
  for (const id of [
    "data-source", "data-equipment", "data-target", "data-start", "data-policy",
    "data-breakthrough",
    "data-count",
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

function sortValue(row, key) {
  if (key === "repriced_mean" || key === "repriced_delta") {
    if (row.repriced === null) {
      // Unknown rows sort last either way rather than pretending to be free.
      return Number.POSITIVE_INFINITY;
    }
    return key === "repriced_mean"
      ? row.repriced
      : row.repriced / row.total_cost_mean;
  }
  if (key.startsWith("p")) {
    return row.total_cost_percentiles[key.slice(1)];
  }
  return row[key];
}

/**
 * Attach each row's mean at today's prices.
 *
 * A marginal run that repairs to 12 stars has to climb back to 22, and that
 * figure comes from the from-scratch dataset - so re-pricing this dataset needs
 * the other one re-priced first. When it is not there, the rows say so instead
 * of quietly keeping the old number.
 */
function withRepricedMeans(rows, prices) {
  const scratch = datasets.simulations;
  const basis = scratch ? rebuildBasis(scratch.results, prices) : new Map();
  return rows.map((row) => {
    const rebuild = basis.has(row.equipment) ? basis.get(row.equipment) : null;
    return { ...row, repriced: repricedMean(row, prices, rebuild) };
  });
}

/**
 * Which scrolls this row's policy actually buys, and where.
 *
 * The policy's name - "最省平均", "只用必中" - says how it was chosen, not what
 * it does, which is the thing worth reading off a table. The full form goes in
 * the tooltip so a folded range can still be checked star by star.
 */
function breakthroughCell(row) {
  const entries = row.breakthrough_entries;
  if (!entries || entries.length === 0) {
    return `<span class="muted">不用</span>`;
  }
  return (
    `<span title="${describe({ entries })}">` +
    `${describeCompact({ entries })}</span>`
  );
}

/** How far today's prices moved this row, against the sweep's snapshot. */
function deltaCell(row) {
  if (row.repriced === null) {
    return "—";
  }
  const ratio = row.repriced / row.total_cost_mean - 1;
  if (Math.abs(ratio) < 0.0005) {
    return "±0%";
  }
  const text = `${ratio > 0 ? "+" : ""}${(ratio * 100).toFixed(1)}%`;
  return `<span class="${ratio > 0 ? "bad-text" : "ok-text"}">${text}</span>`;
}

function render() {
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
  const breakthrough = el["data-breakthrough"].value;

  const modified = store.isModified();
  el.table.querySelectorAll(".repriced").forEach((cell) => {
    cell.hidden = !modified;
  });

  // Sorting defaults to the re-priced mean, which is what the reader is
  // actually after. With untouched prices that column is not shown, so this
  // render falls back to the stored mean without forgetting the default.
  const sorting = !modified && sort.key.startsWith("repriced")
    ? { key: "total_cost_mean", direction: sort.direction }
    : sort;

  const rows = withRepricedMeans(dataset.results, store.currentPrices())
    .filter((row) => equipment === "" || row.equipment === equipment)
    .filter((row) => target === "" || String(row.target_star) === target)
    .filter((row) => start === "" || String(row.start_star) === start)
    .filter((row) => policy === "" || row.repair_policy === policy)
    .filter(
      (row) =>
        breakthrough === "" ||
        (row.breakthrough_policy || "none") === breakthrough
    )
    .sort((a, b) => {
      const left = sortValue(a, sorting.key);
      const right = sortValue(b, sorting.key);
      if (typeof left === "string") {
        return left.localeCompare(right) * sorting.direction;
      }
      return (left - right) * sorting.direction;
    });

  el.body.innerHTML = rows
    .map(
      (row) => `<tr>
        <td>${row.equipment}</td>
        <td class="num">${row.level}</td>
        <td class="num">${row.start_star}</td>
        <td class="num">${row.target_star}</td>
        <td>${POLICY_LABEL[row.repair_policy]}</td>
        <td class="breakthrough">${breakthroughCell(row)}</td>
        <td class="num strong repriced"${modified ? "" : " hidden"}>${
          row.repriced === null ? "—" : formatYi(row.repriced)
        }</td>
        <td class="num repriced"${modified ? "" : " hidden"}>${deltaCell(row)}</td>
        <td class="num">${formatYi(row.total_cost_mean)}</td>
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
  for (const id of [
    "data-equipment",
    "data-target",
    "data-start",
    "data-policy",
    "data-breakthrough",
  ]) {
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
