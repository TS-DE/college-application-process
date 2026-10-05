/* 通用 UI 工具：Toast、Modal、格式化 */
window.UI = (function () {
  function escapeHtml(s) {
    if (s === undefined || s === null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(message, type, ms) {
    const root = document.getElementById("toast-root");
    const el = document.createElement("div");
    el.className = "toast " + (type || "");
    el.innerHTML = escapeHtml(message);
    root.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity .25s, transform .25s";
      el.style.opacity = "0";
      el.style.transform = "translateX(20px)";
      setTimeout(() => el.remove(), 260);
    }, ms || 2600);
  }

  /**
   * 打开弹窗
   * @param {{title:string, body:string, footer?:string, wide?:boolean, onMount?:Function}} opts
   */
  function modal(opts) {
    const root = document.getElementById("modal-root");
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML =
      '<div class="modal' + (opts.wide ? " wide" : "") + '">' +
      '<div class="modal-head"><h3>' + escapeHtml(opts.title) + "</h3>" +
      '<button class="icon-btn js-close">×</button></div>' +
      '<div class="modal-body">' + (opts.body || "") + "</div>" +
      (opts.footer ? '<div class="modal-foot">' + opts.footer + "</div>" : "") +
      "</div>";

    function close() {
      mask.remove();
    }
    mask.querySelector(".js-close").addEventListener("click", close);
    mask.addEventListener("click", (e) => {
      if (e.target === mask) close();
    });
    root.appendChild(mask);
    if (opts.onMount) opts.onMount(mask, close);
    return { el: mask, close, body: mask.querySelector(".modal-body") };
  }

  const fmt = {
    num: (v) => (v === null || v === undefined || v === "" ? "-" : Number(v).toLocaleString("zh-CN")),
    score: (v) => (v === null || v === undefined || v === "" ? "-" : Number(v)),
    money: (v) => (v === null || v === undefined || v === "" ? "-" : Number(v).toLocaleString("zh-CN") + " 元/年"),
    diff: (v) => {
      if (v === null || v === undefined) return "-";
      const n = Number(v);
      return n === 0 ? "持平" : (n > 0 ? "低 " + Math.abs(n).toLocaleString("zh-CN") : "高 " + Math.abs(n).toLocaleString("zh-CN"));
    },
  };

  function schoolTags(item) {
    let html = "";
    if (item.is_985) html += '<span class="tag tag-985">985</span>';
    if (item.is_211) html += '<span class="tag tag-211">211</span>';
    if (item.is_double_first_class && !item.is_985 && !item.is_211) html += '<span class="tag tag-df">双一流</span>';
    if (item.school_nature) html += '<span class="tag tag-gray">' + escapeHtml(item.school_nature) + "</span>";
    if (item.school_province) html += '<span class="tag tag-gray">' + escapeHtml(item.school_province) + "</span>";
    return html;
  }

  function loadingHtml(text) {
    return '<div class="loading"><div class="spinner"></div>' + escapeHtml(text || "加载中…") + "</div>";
  }

  function emptyHtml(text) {
    return '<div class="empty"><div class="empty-icon">🗂</div>' + escapeHtml(text || "暂无数据") + "</div>";
  }

  return { escapeHtml, toast, modal, fmt, schoolTags, loadingHtml, emptyHtml };
})();
