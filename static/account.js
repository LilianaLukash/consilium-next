import { authFetch, fetchAuthMe, getAccessToken } from "./auth-client.js";

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function requireUser() {
  if (!getAccessToken()) {
    window.location.href = "/auth.html";
    return null;
  }
  const me = await fetchAuthMe();
  if (!me || me.mode !== "user") {
    window.location.href = "/auth.html";
    return null;
  }
  return me;
}

function renderTxTable(txs) {
  if (!txs.length) return "<p class=\"field-hint\">Пока нет транзакций</p>";
  const rows = txs
    .map(
      (t) =>
        `<tr><td>${escapeHtml((t.created_at || "").slice(0, 19))}</td><td>${escapeHtml(t.tx_type)}</td><td class="num">${escapeHtml(t.amount_usd)}</td><td>${escapeHtml(t.description || "")}</td></tr>`
    )
    .join("");
  return `<table class="data-table"><thead><tr><th>Дата</th><th>Тип</th><th>Сумма</th><th>Описание</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderUsageTable(logs) {
  if (!logs.length) return "<p class=\"field-hint\">Пока нет списаний</p>";
  const rows = logs
    .map(
      (u) =>
        `<tr><td>${escapeHtml((u.created_at || "").slice(0, 19))}</td><td class="mono">${escapeHtml(u.model)}</td><td class="num">-${escapeHtml(u.client_cost_usd)}</td><td class="num">${u.prompt_tokens}+${u.completion_tokens}</td></tr>`
    )
    .join("");
  return `<table class="data-table"><thead><tr><th>Дата</th><th>Модель</th><th>Списано</th><th>Токены</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function loadAccount() {
  const me = await requireUser();
  if (!me) return;

  const balRes = await authFetch("/api/billing/balance");
  const bal = await balRes.json();
  $("accountBalanceBig").textContent = `$${parseFloat(bal.balance_usd || 0).toFixed(2)}`;

  const txRes = await authFetch("/api/billing/transactions?limit=30");
  const txData = await txRes.json();
  $("txTable").innerHTML = renderTxTable(txData.transactions || []);

  const uRes = await authFetch("/api/billing/usage?limit=30");
  const uData = await uRes.json();
  $("usageTable").innerHTML = renderUsageTable(uData.usage || []);

  document.querySelectorAll(".topup-amt").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const amt = parseFloat(btn.dataset.amt);
      $("topupStatus").textContent = "Перенаправление на Stripe…";
      const res = await authFetch("/api/billing/stripe/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount_usd: amt }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        $("topupStatus").textContent = data.detail || "Ошибка оплаты";
        return;
      }
      if (data.checkout_url) window.location.href = data.checkout_url;
    });
  });
}

loadAccount();
