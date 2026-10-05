/* 应用入口：路由、导航、考生信息、全局搜索、AI 助手 */
window.App = (function () {
  const ROUTES = {
    home: () => Home.render,
    fill: () => Fill.render,
    search: () => Search.render,
    result: () => ResultView.render,
  };

  function routeName() {
    const h = (location.hash || "#/home").replace("#/", "").split("?")[0];
    return ROUTES[h] ? h : "home";
  }

  function render() {
    const name = routeName();
    document.querySelectorAll("#nav-links a").forEach((a) => {
      a.classList.toggle("active", a.dataset.route === name);
    });
    const view = document.getElementById("view");
    ROUTES[name]()(view);
    window.scrollTo({ top: 0 });
  }

  /* ---------------- 考生信息弹窗（与志愿填报第一步共用同一表单） ---------------- */
  function openProfile() {
    const s = Store.student;
    UI.modal({
      title: "请填写您的高考信息",
      wide: true,
      body: '<div id="profile-form-modal"></div>',
      footer: '<button class="btn js-cancel">取消</button><button class="btn btn-primary js-save">保存</button>',
      onMount(mask, close) {
        const form = ProfileForm.render(mask.querySelector("#profile-form-modal"), {
          values: {
            province: s.province,
            grade: s.grade,
            year: s.year,
            first_subject: s.first_subject,
            subjects: s.subjects,
            level: s.level,
            score: s.score,
            rank: s.rank,
            batch: s.batch,
          },
          emptyScore: false,
        });
        form.init();

        mask.querySelector(".js-cancel").addEventListener("click", close);
        mask.querySelector(".js-save").addEventListener("click", () => {
          const v = form.validate();
          if (!v.ok) return UI.toast(v.message, "warn");
          Store.set(v.value);
          UI.toast("考生信息已更新", "success");
          close();
          render();
        });
      },
    });
  }

  /* ---------------- AI 助手抽屉 ---------------- */
  function openAI() {
    document.getElementById("ai-drawer").classList.add("open");
    checkAI();
    const box = document.getElementById("ai-messages");
    if (!box.dataset.init) {
      box.dataset.init = "1";
      pushMsg("bot", "你好！我是本地运行的志愿助手（Qwen3 1.7B）。\n可以问我「冲稳保怎么搭配」「计算机专业怎么选」这类问题。\n注意：我只做解读和表达，录取概率由规则引擎计算。");
    }
    document.getElementById("ai-input").focus();
  }

  function pushMsg(who, text) {
    const box = document.getElementById("ai-messages");
    const el = document.createElement("div");
    el.className = "ai-msg " + who;
    el.textContent = text;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
  }

  async function checkAI() {
    const el = document.getElementById("ai-status");
    try {
      const r = await API.aiStatus();
      el.textContent = r.ollama ? "已连接 " + r.model : "未连接：" + r.message;
      return r.ollama;
    } catch (e) {
      el.textContent = "后端未连接";
      return false;
    }
  }

  async function sendAI() {
    const input = document.getElementById("ai-input");
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    pushMsg("me", text);
    const s = Store.student;
    const ctx = s.province + " " + s.year + " " + s.category + " " + s.batch +
      (s.score ? "，分数 " + s.score : "") + (s.rank ? "，位次 " + s.rank : "");
    pushMsg("bot", "思考中…");
    const holder = document.getElementById("ai-messages").lastChild;
    try {
      const r = await API.chat({ question: text, context: ctx });
      holder.textContent = r.answer;
    } catch (e) {
      holder.textContent = "（" + e.message + "）";
    }
  }

  /* ---------------- 全局搜索 ---------------- */
  async function globalSearch() {
    const text = document.getElementById("global-search").value.trim();
    if (!text) return UI.toast("请输入想查的大学、专业或需求", "warn");
    UI.toast("正在理解你的需求…");
    try {
      const uni = await API.universities({
        province: Store.student.province, year: Store.student.year,
        category: Store.student.category, batch: Store.student.batch,
        keyword: text, page_size: 1, rank: Store.student.rank,
      });
      if (uni.total > 0) {
        window.__searchKeyword = text;
        location.hash = "#/search";
        return;
      }
      const intent = await API.parseIntent({ text: text, province: Store.student.province });
      window.__prefillFilters = intent;
      window.__prefillText = text;
      location.hash = "#/fill";
      UI.toast("已按「" + text + "」预填筛选条件", "success");
    } catch (e) {
      UI.toast(e.message, "error");
    }
  }

  /* ---------------- 初始化 ---------------- */
  function init() {
    Store.refreshChip();
    Store.refreshBook();

    document.getElementById("student-chip").addEventListener("click", openProfile);
    document.getElementById("btn-search").addEventListener("click", globalSearch);
    document.getElementById("global-search").addEventListener("keydown", (e) => {
      if (e.key === "Enter") globalSearch();
    });

    document.getElementById("ai-fab").addEventListener("click", openAI);
    document.getElementById("ai-close").addEventListener("click", () =>
      document.getElementById("ai-drawer").classList.remove("open")
    );
    document.getElementById("ai-send").addEventListener("click", sendAI);
    document.getElementById("ai-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendAI();
    });

    document.getElementById("book-toggle").addEventListener("click", () =>
      document.getElementById("book-panel").classList.remove("show")
    );

    window.addEventListener("hashchange", render);
    render();

    // 后端连通性自检
    API.health()
      .then((r) => {
        if (!r.ollama) UI.toast("Ollama 未连接，AI 功能将自动降级为规则实现", "warn", 4000);
      })
      .catch((e) => UI.toast(e.message, "error", 5000));
  }

  return { init, render, openAI, openProfile };
})();

document.addEventListener("DOMContentLoaded", App.init);
