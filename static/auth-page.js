import { setTokens, clearTokens } from "./auth-client.js";

const $ = (id) => document.getElementById(id);

function showMsg(text, isError = false) {
  const el = $("authMessage");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("hidden", !text);
  el.classList.toggle("is-error", isError);
}

function showForm(name) {
  $("loginForm")?.classList.toggle("hidden", name !== "login");
  $("registerForm")?.classList.toggle("hidden", name !== "register");
  $("resetForm")?.classList.toggle("hidden", name !== "reset");
  $("showRegister")?.classList.toggle("hidden", name === "register");
  $("showLogin")?.classList.toggle("hidden", name !== "register");
}

const params = new URLSearchParams(window.location.search);
if (params.get("verify")) {
  fetch("/api/auth/verify-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: params.get("verify") }),
  })
    .then((r) => r.json())
    .then((d) => showMsg(d.message || "Email подтверждён"))
    .catch(() => showMsg("Ошибка подтверждения", true));
  showForm("login");
} else if (params.get("reset")) {
  showForm("reset");
} else if (params.get("access_token")) {
  setTokens(params.get("access_token"), params.get("refresh_token"));
  window.location.href = "/";
} else {
  showForm("login");
}

$("showRegister")?.addEventListener("click", () => showForm("register"));
$("showLogin")?.addEventListener("click", () => showForm("login"));

$("loginForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: $("loginEmail").value.trim(),
      password: $("loginPassword").value,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showMsg(data.detail?.message || data.detail || "Ошибка входа", true);
    return;
  }
  setTokens(data.access_token, data.refresh_token);
  window.location.href = "/";
});

$("registerForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: $("regEmail").value.trim(),
      password: $("regPassword").value,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showMsg(data.detail?.message || "Ошибка регистрации", true);
    return;
  }
  showMsg(data.message || "Проверьте почту");
  showForm("login");
});

$("resetForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await fetch("/api/auth/reset-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      token: params.get("reset"),
      password: $("resetPassword").value,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showMsg(data.detail?.message || "Ошибка", true);
    return;
  }
  showMsg("Пароль обновлён. Войдите.");
  showForm("login");
});
