// The normal run.py server is unchanged: no fragment, no lifecycle connection.
(() => {
  const token = new URLSearchParams(location.hash.slice(1)).get("desktop");
  if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) return;
  let source = null;
  const badge = document.querySelector(".badge");
  const status = (state, text) => {
    document.documentElement.dataset.desktop = state;
    badge.textContent = text;
  };
  function connect() {
    if (source) return;
    status("connecting", "Offline · 正在连接便携程序…");
    source = new EventSource(`/api/desktop/events?token=${encodeURIComponent(token)}`);
    source.onopen = () => status("connected", "Offline · 关闭最后一个程序页后自动退出");
    source.onerror = () => status("disconnected", "连接中断 · 若未恢复，请重新双击程序");
    badge.title = "仅离线合成，不连接仪器。刷新有 5 秒重连宽限；多开程序页需全部关闭。关闭前请按需导出。";
  }
  window.addEventListener("pagehide", () => {
    source?.close();
    source = null;
  });
  // Also reconnect after back/forward cache restoration; keep the fragment so
  // refresh and duplicate-tab operations use this same application instance.
  window.addEventListener("pageshow", connect);
  connect();
})();
