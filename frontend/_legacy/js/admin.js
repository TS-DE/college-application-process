/* 后台知识库管理页逻辑（独立于考生端 SPA） */
(function () {
  const TOKEN_KEY = "gaokao_admin_token";

  const el = (id) => document.getElementById(id);
  const token = () => localStorage.getItem(TOKEN_KEY) || "";

  function fmtSize(n) {
    if (n == null) return "-";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(2) + " MB";
  }

  function toast(msg, type) {
    const box = el("toast-box");
    if (!box) return alert(msg);
    const t = document.createElement("div");
    t.className = "toast " + (type || "info");
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(() => {
      t.classList.add("hide");
      setTimeout(() => t.remove(), 300);
    }, 2600);
  }

  async function api(path, options) {
    const opt = options || {};
    opt.headers = Object.assign({}, opt.headers, { Authorization: "Bearer " + token() });
    if (opt.body && !(opt.body instanceof FormData) && typeof opt.body !== "string") {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(opt.body);
    }
    const resp = await fetch("/api/knowledge" + path, opt);
    if (resp.status === 401) {
      showLogin();
      throw new Error("登录已过期，请重新登录");
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || "请求失败");
    return data;
  }

  /* ---------------- 视图切换 ---------------- */
  function showLogin() {
    localStorage.removeItem(TOKEN_KEY);
    el("login-view").classList.remove("hidden");
    el("admin-view").classList.add("hidden");
  }

  function showAdmin(user) {
    el("login-view").classList.add("hidden");
    el("admin-view").classList.remove("hidden");
    el("admin-name").textContent = user.username + "（管理员）";
    loadList();
  }

  async function bootstrap() {
    if (!token()) return showLogin();
    try {
      const resp = await fetch("/api/auth/me", {
        headers: { Authorization: "Bearer " + token() },
      });
      const data = await resp.json();
      if (resp.ok && data.user && data.user.role === "admin") return showAdmin(data.user);
      showLogin();
    } catch (e) {
      showLogin();
    }
  }

  /* ---------------- 登录 ---------------- */
  el("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    el("login-error").textContent = "";
    try {
      const resp = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: el("login-username").value.trim(),
          password: el("login-password").value,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "登录失败");
      if (data.user.role !== "admin") throw new Error("该账号不是管理员");
      localStorage.setItem(TOKEN_KEY, data.token);
      showAdmin(data.user);
    } catch (err) {
      el("login-error").textContent = err.message;
    }
  });

  el("logout-btn").addEventListener("click", showLogin);

  /* ---------------- 列表 ---------------- */
  async function loadList(keyword) {
    const tbody = el("kb-tbody");
    tbody.innerHTML = '<tr><td colspan="4" class="empty">加载中…</td></tr>';
    try {
      const qs = keyword ? "?keyword=" + encodeURIComponent(keyword) : "";
      const data = await api("/list" + qs);
      if (!data.items.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty">暂无文件，点击左上角「上传」</td></tr>';
        return;
      }
      tbody.innerHTML = data.items
        .map(
          (it) =>
            "<tr>" +
            '<td style="max-width:420px;word-break:break-all">' + it.filename + "</td>" +
            "<td>" + fmtSize(it.size) + "</td>" +
            "<td>" + (it.upload_time || "-") + "</td>" +
            '<td><div class="op">' +
            '<a data-act="detail" data-id="' + it.id + '">详情</a>' +
            '<a data-act="delete" data-id="' + it.id + '" class="danger">删除</a>' +
            "</div></td></tr>"
        )
        .join("");
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty">' + err.message + "</td></tr>";
    }
  }

  el("kb-tbody").addEventListener("click", async (e) => {
    const a = e.target.closest("a[data-act]");
    if (!a) return;
    const id = a.dataset.id;
    if (a.dataset.act === "detail") {
      try {
        const d = await api("/detail/" + id);
        showModal(
          "文件详情",
          [
            ["文件名", d.filename],
            ["大小", fmtSize(d.size)],
            ["类型", d.content_type || "-"],
            ["上传时间", d.upload_time || "-"],
            ["状态", d.status],
            ["存储名", d.stored_name],
          ]
        );
      } catch (err) {
        toast(err.message, "error");
      }
    } else if (a.dataset.act === "delete") {
      if (!confirm("确定删除该文件？删除后不可恢复。")) return;
      try {
        await api("/delete/" + id, { method: "DELETE" });
        toast("已删除", "success");
        loadList(el("search-input").value.trim());
      } catch (err) {
        toast(err.message, "error");
      }
    }
  });

  /* ---------------- 上传 ---------------- */
  el("upload-btn").addEventListener("click", () => el("file-input").click());

  el("file-input").addEventListener("change", async () => {
    const file = el("file-input").files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    toast("正在上传：" + file.name);
    try {
      const data = await api("/upload", { method: "POST", body: fd });
      toast(data.message || "上传成功", "success");
      loadList(el("search-input").value.trim());
    } catch (err) {
      toast(err.message, "error");
    } finally {
      el("file-input").value = "";
    }
  });

  /* ---------------- 搜索 ---------------- */
  el("search-btn").addEventListener("click", () => loadList(el("search-input").value.trim()));
  el("search-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadList(el("search-input").value.trim());
  });

  /* ---------------- 详情弹窗 ---------------- */
  function showModal(title, rows) {
    const mask = document.createElement("div");
    mask.className = "modal-mask";
    mask.innerHTML =
      '<div class="modal-card"><h3>' + title + "</h3>" +
      rows.map((r) => '<div class="detail-row"><span class="k">' + r[0] + '</span><span class="v">' + r[1] + "</span></div>").join("") +
      '<div style="margin-top:16px;text-align:right"><button class="btn btn-primary js-close">关闭</button></div></div>';
    document.body.appendChild(mask);
    mask.querySelector(".js-close").addEventListener("click", () => mask.remove());
    mask.addEventListener("click", (e) => {
      if (e.target === mask) mask.remove();
    });
  }

  bootstrap();
})();
