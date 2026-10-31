/* Smart Inventory Intelligence - front-end (vanilla JS + Chart.js) */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const inr = n => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
const num = n => Number(n || 0).toLocaleString("en-IN");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PALETTE = ["#2b5cff", "#12a150", "#e8a000", "#e5484d", "#8a5cf6", "#0ea5b7", "#f06a2b", "#64748b"];

async function api(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}
const post = (url, body, method = "POST") =>
  api(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(msg, ok = true) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + (ok ? "ok" : "err");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}

/* generic table renderer: cols = [{h, k|fn, num, html}] */
function renderTable(el, cols, data, empty = "No data") {
  if (!data.length) { el.innerHTML = `<tr><td class="muted">${empty}</td></tr>`; return; }
  el.innerHTML =
    "<thead><tr>" + cols.map(c => `<th class="${c.num ? "num" : ""}">${c.h}</th>`).join("") + "</tr></thead><tbody>" +
    data.map(r => "<tr>" + cols.map(c => {
      const v = c.fn ? c.fn(r) : r[c.k];
      return `<td class="${c.num ? "num" : ""}">${c.html ? v : esc(v)}</td>`;
    }).join("") + "</tr>").join("") + "</tbody>";
}
const pill = (txt, cls = txt) => `<span class="pill ${cls}">${esc(txt)}</span>`;

/* ---------------- charts ---------------- */
const charts = {};
function chart(id, cfg) {
  if (typeof Chart === "undefined") {
    $("#" + id).parentElement.innerHTML = '<p class="muted">Charts need internet access to load Chart.js.</p>';
    return;
  }
  charts[id]?.destroy();
  charts[id] = new Chart($("#" + id), cfg);
}
const baseOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } } };

/* ---------------- navigation ---------------- */
const loaders = {
  dashboard: loadDashboard, products: loadProducts, movements: loadMovements,
  reorder: loadReorder, analytics: loadAnalytics, suppliers: loadSuppliers, sql: loadSqlSamples,
};
function showTab(name) {
  $$("#nav button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("hidden", t.id !== "tab-" + name));
  loaders[name]?.();
}
$("#nav").addEventListener("click", e => { const b = e.target.closest("button"); if (b) showTab(b.dataset.tab); });

/* ---------------- dashboard ---------------- */
async function loadDashboard() {
  const [k, trend, cats, top, alerts] = await Promise.all([
    api("/api/kpis"), api("/api/sales-trend?days=60"), api("/api/category-summary"),
    api("/api/top-products"), api("/api/alerts"),
  ]);
  $("#asOf").textContent = "As of " + new Date().toLocaleDateString("en-IN", { dateStyle: "medium" });
  const g = k.revenue_growth_pct;
  const growth = g == null ? "" : `<span class="${g >= 0 ? "up" : "down"}">${g >= 0 ? "▲" : "▼"} ${Math.abs(g)}%</span> vs previous 30 days`;
  const cards = [
    ["Inventory value (cost)", inr(k.cost_value), `${k.products} active products`],
    ["Revenue · 30 days", inr(k.revenue_30d), growth],
    ["Profit · 30 days", inr(k.profit_30d), `${k.margin_pct}% margin`],
    ["Units sold · 30 days", num(k.units_30d), `retail value of stock ${inr(k.retail_value)}`],
    ["Low / out of stock", `${k.low_stock} / ${k.out_of_stock}`, "need attention"],
    ["Dead stock", inr(k.dead_value), `${k.dead_items} items, no sale in 60 days`],
  ];
  $("#kpis").innerHTML = cards.map(c => `<div class="kpi"><div class="label">${c[0]}</div><div class="value">${c[1]}</div><div class="sub">${c[2]}</div></div>`).join("");

  chart("trendChart", {
    type: "line",
    data: {
      labels: trend.map(r => r.day.slice(5)),
      datasets: [
        { label: "Daily revenue", data: trend.map(r => r.revenue), borderColor: "#9db4ff", backgroundColor: "rgba(43,92,255,.08)", fill: true, tension: .25, pointRadius: 0 },
        { label: "7-day avg", data: trend.map(r => r.moving_avg_7d), borderColor: "#2b5cff", borderWidth: 2.5, tension: .3, pointRadius: 0 },
      ],
    },
    options: { ...baseOpts, scales: { x: { ticks: { maxTicksLimit: 10 } }, y: { ticks: { callback: v => "₹" + v / 1000 + "k" } } } },
  });
  chart("catChart", {
    type: "doughnut",
    data: { labels: cats.map(c => c.category), datasets: [{ data: cats.map(c => c.revenue_90d), backgroundColor: PALETTE }] },
    options: baseOpts,
  });
  chart("topChart", {
    type: "bar",
    data: { labels: top.map(t => t.name), datasets: [{ label: "Revenue", data: top.map(t => t.revenue), backgroundColor: "#2b5cff", borderRadius: 5 }] },
    options: { ...baseOpts, indexAxis: "y", plugins: { legend: { display: false } } },
  });
  $("#alertList").innerHTML = alerts.length
    ? alerts.map(a => `<div class="alert"><span class="dot ${a.alert_type}"></span><div>${esc(a.message)}<div class="muted small">${esc(a.sku)} · ${esc(a.created_at.slice(0, 10))}</div></div></div>`).join("")
    : '<p class="muted">All good - no active alerts 🎉</p>';
  const badge = $("#alertBadge");
  badge.textContent = alerts.length;
  badge.classList.toggle("hidden", !alerts.length);
}

/* ---------------- products ---------------- */
let lookups = null;
async function ensureLookups() {
  if (lookups) return lookups;
  lookups = await api("/api/lookups");
  const opts = lookups.categories.map(c => `<option>${esc(c.name)}</option>`).join("");
  $("#pCategory").insertAdjacentHTML("beforeend", opts);
  $("#fCategory").innerHTML = lookups.categories.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  $("#fSupplier").innerHTML = lookups.suppliers.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("");
  return lookups;
}
let productCache = [];
async function loadProducts() {
  await ensureLookups();
  const p = new URLSearchParams({ q: $("#pSearch").value, status: $("#pStatus").value, category: $("#pCategory").value });
  productCache = await api("/api/products?" + p);
  renderTable($("#productTable"), [
    { h: "SKU", k: "sku" }, { h: "Product", k: "name" }, { h: "Category", k: "category" },
    { h: "Supplier", k: "supplier" },
    { h: "Cost", fn: r => inr(r.unit_cost), num: 1 }, { h: "Price", fn: r => inr(r.unit_price), num: 1 },
    { h: "Stock", fn: r => num(r.stock_qty), num: 1 }, { h: "Reorder at", k: "reorder_level", num: 1 },
    { h: "Status", fn: r => pill(r.status), html: 1 },
    { h: "", fn: r => `<button class="btn sm" data-edit="${r.product_id}">Edit</button> <button class="btn sm danger" data-del="${r.product_id}">Delete</button>`, html: 1 },
  ], productCache, "No products match.");
}
["input", "change"].forEach(ev => {
  $("#pSearch").addEventListener(ev, debounce(loadProducts, 250));
  $("#pStatus").addEventListener(ev, loadProducts);
  $("#pCategory").addEventListener(ev, loadProducts);
});
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function openModal(p) {
  const f = $("#productForm");
  f.reset();
  $("#modalTitle").textContent = p ? "Edit product" : "Add product";
  $("#openingWrap").classList.toggle("hidden", !!p);
  if (p) {
    f.product_id.value = p.product_id; f.name.value = p.name;
    f.category_id.value = lookups.categories.find(c => c.name === p.category)?.id;
    f.supplier_id.value = lookups.suppliers.find(s => s.name === p.supplier)?.id;
    f.unit_cost.value = p.unit_cost; f.unit_price.value = p.unit_price;
    f.reorder_level.value = p.reorder_level; f.reorder_qty.value = p.reorder_qty;
  } else f.product_id.value = "";
  $("#modal").classList.remove("hidden");
}
$("#addProductBtn").onclick = async () => { await ensureLookups(); openModal(null); };
$("#cancelModal").onclick = () => $("#modal").classList.add("hidden");
$("#productTable").addEventListener("click", async e => {
  const ed = e.target.closest("[data-edit]"), del = e.target.closest("[data-del]");
  if (ed) openModal(productCache.find(p => p.product_id == ed.dataset.edit));
  if (del && confirm("Remove this product from the active list? (History is kept.)")) {
    try { await api("/api/products/" + del.dataset.del, { method: "DELETE" }); toast("Product removed"); loadProducts(); }
    catch (err) { toast(err.message, false); }
  }
});
$("#productForm").addEventListener("submit", async e => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  try {
    if (d.product_id) await post("/api/products/" + d.product_id, d, "PUT");
    else await post("/api/products", d);
    $("#modal").classList.add("hidden");
    toast("Product saved");
    loadProducts();
  } catch (err) { toast(err.message, false); }
});

/* ---------------- movements ---------------- */
async function loadMovements() {
  const [prods, moves] = await Promise.all([api("/api/products"), api("/api/movements?limit=50")]);
  const sel = $("#mProduct");
  const keep = sel.value;
  sel.innerHTML = prods.map(p => `<option value="${p.product_id}">${esc(p.name)} (stock ${p.stock_qty})</option>`).join("");
  if (keep) sel.value = keep;
  renderTable($("#moveTable"), [
    { h: "When", fn: r => r.created_at.slice(0, 16) }, { h: "SKU", k: "sku" }, { h: "Product", k: "name" },
    { h: "Type", fn: r => pill(r.movement_type, r.movement_type === "OUT" ? "OUTMOVE" : r.movement_type), html: 1 },
    { h: "Qty", k: "quantity", num: 1 }, { h: "Unit price", fn: r => inr(r.unit_price), num: 1 }, { h: "Note", fn: r => r.note || "" },
  ], moves);
}
$("#moveForm").addEventListener("submit", async e => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(e.target));
  try {
    const r = await post("/api/movements", d);
    toast("Saved - new stock level: " + r.stock_qty);
    e.target.quantity.value = ""; e.target.note.value = "";
    loadMovements();
  } catch (err) { toast(err.message, false); }
});

/* ---------------- reorder ---------------- */
async function loadReorder() {
  const [r, f] = await Promise.all([api("/api/reorder-suggestions"), api("/api/forecast")]);
  renderTable($("#reorderTable"), [
    { h: "Priority", fn: x => pill(x.priority), html: 1 }, { h: "Product", k: "name" }, { h: "Supplier", k: "supplier" },
    { h: "Stock", k: "stock_qty", num: 1 }, { h: "Reorder at", k: "reorder_level", num: 1 },
    { h: "Avg sales/day", k: "avg_daily_sales", num: 1 }, { h: "Days of cover", fn: x => x.days_of_cover ?? "-", num: 1 },
    { h: "Lead time", fn: x => x.lead_time_days + " d", num: 1 },
    { h: "Suggested order", k: "suggested_order_qty", num: 1 }, { h: "Est. cost", fn: x => inr(x.estimated_cost), num: 1 },
  ], r, "Nothing to reorder right now.");
  renderTable($("#forecastTable"), [
    { h: "Product", k: "name" }, { h: "Stock", k: "stock_qty", num: 1 },
    { h: "Forecast/day", k: "forecast_daily", num: 1 }, { h: "Next 30 days", k: "forecast_next_30d", num: 1 },
    { h: "Expected stock-out", k: "stockout_date" },
  ], f);
}

/* ---------------- analytics ---------------- */
async function loadAnalytics() {
  const [abc, dead, turn] = await Promise.all([api("/api/abc-analysis"), api("/api/dead-stock"), api("/api/turnover")]);
  const colors = { A: "#12a150", B: "#e8a000", C: "#94a3b8" };
  chart("abcChart", {
    data: {
      labels: abc.map(a => a.name),
      datasets: [
        { type: "bar", label: "Revenue", data: abc.map(a => a.revenue), backgroundColor: abc.map(a => colors[a.abc_class]), yAxisID: "y", borderRadius: 3 },
        { type: "line", label: "Cumulative %", data: abc.map(a => a.cumulative_pct), borderColor: "#1b2333", pointRadius: 0, yAxisID: "y1", tension: .2 },
      ],
    },
    options: { ...baseOpts, scales: { x: { display: false }, y: { ticks: { callback: v => "₹" + v / 1000 + "k" } }, y1: { position: "right", min: 0, max: 100, grid: { drawOnChartArea: false } } } },
  });
  const cls = { A: [0, 0], B: [0, 0], C: [0, 0] };
  abc.forEach(a => { cls[a.abc_class][0]++; cls[a.abc_class][1] += a.share_pct; });
  $("#abcSummary").innerHTML = Object.entries(cls).map(([k, v]) =>
    `<span class="chip static">${pill(k)} ${v[0]} items · ${v[1].toFixed(0)}% of revenue</span>`).join("");
  renderTable($("#abcTable"), [
    { h: "#", k: "rank" }, { h: "Class", fn: a => pill(a.abc_class), html: 1 }, { h: "Product", k: "name" }, { h: "Category", k: "category" },
    { h: "Units (90d)", k: "units", num: 1 }, { h: "Revenue", fn: a => inr(a.revenue), num: 1 },
    { h: "Share", fn: a => a.share_pct + "%", num: 1 }, { h: "Cumulative", fn: a => a.cumulative_pct + "%", num: 1 },
  ], abc);
  renderTable($("#deadTable"), [
    { h: "Product", k: "name" }, { h: "Stock", k: "stock_qty", num: 1 }, { h: "Value locked", fn: d => inr(d.stock_value), num: 1 },
    { h: "Last sale", fn: d => d.last_sale || "never" },
  ], dead, "No dead stock 🎉");
  renderTable($("#turnTable"), [
    { h: "Product", k: "name" }, { h: "Category", k: "category" }, { h: "Stock value", fn: t => inr(t.stock_value), num: 1 },
    { h: "Sold (90d)", k: "units_sold_90d", num: 1 }, { h: "Turnover (x/yr)", fn: t => t.turnover_ratio ?? "-", num: 1 },
    { h: "Days to sell out", fn: t => t.days_to_sell_out ?? "-", num: 1 },
    { h: "Speed", fn: t => ["", "Fast", "Good", "Slow", "Very slow"][t.speed_quartile] },
  ], turn);
}

/* ---------------- suppliers ---------------- */
async function loadSuppliers() {
  renderTable($("#supplierTable"), [
    { h: "Supplier", k: "name" }, { h: "Email", k: "contact_email" }, { h: "Phone", k: "phone" },
    { h: "Lead time", fn: s => s.lead_time_days + " days", num: 1 }, { h: "Products", k: "products", num: 1 },
    { h: "Stock value", fn: s => inr(s.stock_value), num: 1 }, { h: "Items to reorder", k: "items_to_reorder", num: 1 },
  ], await api("/api/suppliers"));
}

/* ---------------- SQL explorer ---------------- */
let samplesLoaded = false;
async function loadSqlSamples() {
  if (samplesLoaded) return;
  samplesLoaded = true;
  const s = await api("/api/sql-samples");
  $("#samples").innerHTML = s.map((q, i) => `<button class="chip" data-i="${i}">${esc(q.title)}</button>`).join("");
  $("#samples").onclick = e => {
    const b = e.target.closest(".chip");
    if (b) { $("#sqlBox").value = s[b.dataset.i].sql; runSql(); }
  };
}
async function runSql() {
  const t0 = performance.now();
  try {
    const r = await post("/api/sql", { sql: $("#sqlBox").value });
    $("#sqlInfo").textContent = `${r.rows.length} rows${r.truncated ? " (truncated)" : ""} · ${(performance.now() - t0).toFixed(0)} ms`;
    renderTable($("#sqlResult"), r.columns.map((c, i) => ({ h: esc(c), fn: row => row[i] ?? "NULL", html: 0 })),
      r.rows.map(x => x), "Query returned no rows.");
    // header labels were pre-escaped; table cells escape their own values
  } catch (err) {
    $("#sqlInfo").textContent = "";
    $("#sqlResult").innerHTML = `<tr><td class="down">${esc(err.message)}</td></tr>`;
  }
}
$("#runSql").onclick = runSql;
$("#sqlBox").addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runSql(); });

/* ---------------- boot ---------------- */
showTab("dashboard");
