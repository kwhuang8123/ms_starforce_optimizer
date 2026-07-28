/**
 * Boot: load the generated data, wire the tabs, hand each tab its slice.
 *
 * Everything under data/ is produced by build_site_data.py from the Python
 * package, so the front end never carries its own copy of a rule or a price.
 */

import * as rules from "./rules.js";
import * as store from "./prices-store.js";
import { initPlay } from "./ui-play.js";
import { initData } from "./ui-data.js";
import { initPrices } from "./ui-prices.js";

async function loadJson(path, { required = true } = {}) {
  const response = await fetch(path);
  if (!response.ok) {
    if (required) {
      throw new Error(`無法載入 ${path}（HTTP ${response.status}）`);
    }
    return null;
  }
  return response.json();
}

function initTabs() {
  const buttons = document.querySelectorAll(".tab");
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      buttons.forEach((other) => other.classList.toggle("active", other === button));
      document.querySelectorAll(".panel").forEach((panel) => {
        panel.hidden = panel.id !== `tab-${button.dataset.tab}`;
      });
    });
  });
}

function renderFooter(datasets) {
  const parts = [];
  for (const [label, dataset] of [
    ["從零開始", datasets.simulations],
    ["已持有", datasets.marginal],
  ]) {
    parts.push(dataset ? `${label} ${dataset.meta.generated_at}` : `${label} 尚未產生`);
  }
  document.getElementById("footer-meta").textContent = `資料集：${parts.join("　|　")}`;
}

async function boot() {
  const [staticData, shippedPrices, simulations, marginal] = await Promise.all([
    loadJson("data/static.json"),
    loadJson("data/prices.json"),
    loadJson("data/simulations.json", { required: false }),
    loadJson("data/marginal.json", { required: false }),
  ]);

  const prices = store.init(shippedPrices);
  rules.configure(staticData, prices);
  store.onChange((updated) => rules.setPrices(updated));

  const datasets = { simulations, marginal };
  initTabs();
  initPrices();
  initPlay(datasets);
  initData(datasets);
  renderFooter(datasets);
}

boot().catch((error) => {
  const banner = document.getElementById("boot-error");
  banner.hidden = false;
  banner.textContent =
    `${error.message}。這個頁面需要透過 HTTP 開啟（GitHub Pages 或 ` +
    `python -m http.server -d docs 8000），直接雙擊 HTML 檔案不會運作。`;
});
