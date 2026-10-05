/* 首页：中国地图 + 热门院校 + 快捷工具 */
window.Home = (function () {
  let chart = null;
  let statsCache = null;
  let currentProvince = null;

  function template() {
    return (
      '<section class="home-hero">' +
      "<div>" +
      "<h1>用位次说话，科学填满 48 个志愿</h1>" +
      "<p>基于河南 2024-2025 年真实录取数据，规则引擎负责计算冲稳保，本地大模型负责理解与表达。</p>" +
      "</div>" +
      '<div class="hero-stats">' +
      '<div class="hero-stat"><b id="stat-major">-</b><span>在豫招生专业</span></div>' +
      '<div class="hero-stat"><b id="stat-school">-</b><span>招生院校</span></div>' +
      '<div class="hero-stat"><b id="stat-prov">-</b><span>覆盖省份</span></div>' +
      "</div>" +
      "</section>" +

      '<div class="home-layout">' +
      "<div>" +
      '<div class="card map-card">' +
      '<div class="card-title"><h3>全国高校分布地图</h3>' +
      '<span class="sub" id="map-tip">点击省份查看在河南招生的高校</span></div>' +
      '<div id="china-map"></div>' +
      "</div>" +
      '<div id="province-result" style="margin-top:20px"></div>' +
      '<div class="card" style="margin-top:20px">' +
      '<div class="card-title"><h3>热门院校推荐</h3><span class="sub">按投档位次排序，985/211 优先</span></div>' +
      '<div class="school-grid" id="hot-schools">' +
      UI.loadingHtml() +
      "</div>" +
      "</div>" +
      "</div>" +

      "<aside>" +
      '<div class="card">' +
      '<div class="card-title"><h3>快捷工具</h3></div>' +
      '<div class="tool-list">' +
      '<button class="tool-item js-tool" data-tool="score2rank"><span class="tool-icon">📊</span>' +
      "<span><b>一分一段查询</b><span>输入分数看全省位次</span></span></button>" +
      '<button class="tool-item js-tool" data-tool="rank2score"><span class="tool-icon">🎯</span>' +
      "<span><b>位次反查分数</b><span>同位次往年去了哪些分</span></span></button>" +
      '<button class="tool-item js-tool" data-tool="control"><span class="tool-icon">📏</span>' +
      "<span><b>省控线</b><span>本科批 / 专科批分数线</span></span></button>" +
      '<button class="tool-item js-tool" data-tool="table"><span class="tool-icon">📋</span>' +
      "<span><b>一分一段表</b><span>查看完整分数段人数</span></span></button>" +
      '<button class="tool-item js-tool" data-tool="ai"><span class="tool-icon">🤖</span>' +
      "<span><b>AI 志愿助手</b><span>自然语言提问</span></span></button>" +
      "</div>" +
      "</div>" +

      '<div class="card" style="margin-top:20px">' +
      '<div class="card-title"><h3>我的志愿表</h3><span class="sub" id="book-count-mini">0 条</span></div>' +
      '<div style="display:flex;gap:8px">' +
      '<button class="btn btn-sm js-show-book">查看志愿表</button>' +
      '<button class="btn btn-sm btn-ghost js-clear-book">清空</button>' +
      "</div></div>" +
      "</aside>" +
      "</div>"
    );
  }

  async function render(container) {
    container.innerHTML = template();
    bindTools(container);
    Store.refreshBook();
    loadStats();
    loadHotSchools();
    loadMap();
  }

  function dims() {
    const s = Store.student;
    return { province: s.province, year: s.year, category: s.category, batch: s.batch };
  }

  async function loadStats() {
    try {
      const [ps, univ] = await Promise.all([
        API.provinceStats(dims()),
        API.universities(Object.assign({ page_size: 1 }, dims(), { rank: Store.student.rank })),
      ]);
      statsCache = ps.items;
      const total = ps.items.reduce((a, b) => a + b.value, 0);
      document.getElementById("stat-major").textContent = total.toLocaleString("zh-CN");
      document.getElementById("stat-school").textContent = univ.total || "-";
      document.getElementById("stat-prov").textContent = ps.items.length;
    } catch (e) {
      UI.toast("统计信息加载失败：" + e.message, "error");
    }
  }

  async function loadHotSchools() {
    const box = document.getElementById("hot-schools");
    try {
      const data = await API.hotSchools(Object.assign({ limit: 12 }, dims()));
      if (!data.items.length) {
        box.innerHTML = UI.emptyHtml("暂无热门院校数据");
        return;
      }
      box.innerHTML = data.items
        .map(
          (s) =>
            '<div class="school-card"><h4>' +
            UI.escapeHtml(s.university_name) +
            "</h4>" +
            '<div style="margin:6px 0">' +
            UI.schoolTags({ is_985: s.tags.includes("985"), is_211: s.tags.includes("211"), school_nature: s.school_nature, school_province: s.school_province }) +
            "</div>" +
            '<div class="nums">' +
            "<div><b>" + UI.fmt.score(s.min_score) + "</b>最低分</div>" +
            "<div><b>" + UI.fmt.num(s.min_rank) + "</b>最低位次</div>" +
            "</div></div>"
        )
        .join("");
    } catch (e) {
      box.innerHTML = UI.emptyHtml(e.message);
    }
  }

  async function loadMap() {
    const el = document.getElementById("china-map");
    if (!el) return;
    if (typeof echarts === "undefined") {
      el.innerHTML = UI.emptyHtml("地图组件未加载（assets/vendor/echarts.min.js 缺失）");
      return;
    }
    let items = statsCache || [];
    if (!items.length) {
      try {
        items = (await API.provinceStats(dims())).items;
        statsCache = items;
      } catch (e) {
        items = [];
      }
    }
    const max = Math.max.apply(null, items.map((i) => i.value).concat([1]));

    chart = echarts.init(el);
    chart.setOption({
      tooltip: {
        trigger: "item",
        formatter: (p) => (p.value ? p.name + "：在豫招生 " + p.value + " 个专业" : p.name + "：暂无数据"),
      },
      visualMap: {
        min: 0,
        max: max,
        left: 12,
        bottom: 12,
        text: ["多", "少"],
        calculable: true,
        inRange: { color: ["#e0e7ff", "#a5b4fc", "#6366f1", "#4338ca"] },
        textStyle: { fontSize: 11 },
      },
      series: [
        {
          name: "在豫招生专业数",
          type: "map",
          mapType: "china",
          roam: false,
          zoom: 1.15,
          itemStyle: { areaColor: "#f1f5f9", borderColor: "#cbd5e1", borderWidth: 0.6 },
          emphasis: { itemStyle: { areaColor: "#f59e0b" }, label: { color: "#fff" } },
          label: { show: true, fontSize: 9, color: "#475569" },
          data: items,
        },
      ],
    });
    chart.on("click", (p) => {
      if (!p.name) return;
      showProvince(p.name);
    });
    if (!window.__mapResizeBound) {
      window.__mapResizeBound = true;
      window.addEventListener("resize", () => chart && chart.resize());
    }
  }

  async function showProvince(name) {
    currentProvince = name;
    const box = document.getElementById("province-result");
    document.getElementById("map-tip").textContent = "已选择：" + name;
    box.innerHTML =
      '<div class="card"><div class="card-title"><h3>' +
      UI.escapeHtml(name) +
      ' 高校（在' + UI.escapeHtml(Store.student.province) + '招生）</h3>' +
      '<button class="btn btn-sm btn-ghost js-close-prov">关闭</button></div>' +
      '<div class="school-grid" id="prov-schools">' + UI.loadingHtml() + "</div></div>";
    box.querySelector(".js-close-prov").addEventListener("click", () => {
      box.innerHTML = "";
      document.getElementById("map-tip").textContent = "点击省份查看在河南招生的高校";
    });

    try {
      const data = await API.universities(
        Object.assign({ school_province: name, page_size: 12, rank: Store.student.rank }, dims())
      );
      const grid = document.getElementById("prov-schools");
      if (!data.items.length) {
        grid.innerHTML = UI.emptyHtml("该省份暂无在豫招生院校数据");
        return;
      }
      grid.innerHTML = data.items
        .map(
          (s) =>
            '<div class="school-card"><h4>' + UI.escapeHtml(s.university_name) + "</h4>" +
            '<div style="margin:6px 0">' + UI.schoolTags(s) +
            (s.tier_label ? '<span class="tier-chip tier-' + s.tier + '">' + s.tier_label + "</span>" : "") +
            "</div>" +
            '<div class="nums">' +
            "<div><b>" + UI.fmt.score(s.min_score) + "</b>最低分</div>" +
            "<div><b>" + UI.fmt.num(s.min_rank) + "</b>最低位次</div>" +
            (s.probability ? "<div><b>" + s.probability + "%</b>预估概率</div>" : "") +
            "</div></div>"
        )
        .join("");
    } catch (e) {
      document.getElementById("prov-schools").innerHTML = UI.emptyHtml(e.message);
    }
  }

  function bindTools(container) {
    container.querySelectorAll(".js-tool").forEach((btn) => {
      btn.addEventListener("click", () => {
        const t = btn.dataset.tool;
        if (t === "ai") return App.openAI();
        if (t === "control") return toolControl();
        if (t === "score2rank") return toolScore2Rank();
        if (t === "rank2score") return toolRank2Score();
        if (t === "table") return toolTable();
      });
    });
    const clear = container.querySelector(".js-clear-book");
    if (clear) clear.addEventListener("click", () => { Store.clearBook(); UI.toast("志愿表已清空"); });
    const showBook = container.querySelector(".js-show-book");
    if (showBook) {
      showBook.addEventListener("click", () => {
        const panel = document.getElementById("book-panel");
        panel.classList.add("show");
        Store.refreshBook();
      });
    }
  }

  function dimFields() {
    const s = Store.student;
    return (
      '<input type="hidden" name="province" value="' + s.province + '">' +
      '<div class="grid-2">' +
      '<div class="field"><label>年份</label><select name="year"><option value="2025" ' + (s.year == 2025 ? "selected" : "") + '>2025</option><option value="2024" ' + (s.year == 2024 ? "selected" : "") + '>2024</option></select></div>' +
      '<div class="field"><label>科类</label><select name="category"><option value="物理类" ' + (s.category === "物理类" ? "selected" : "") + '>物理类（2025）</option><option value="历史类" ' + (s.category === "历史类" ? "selected" : "") + '>历史类（2025）</option><option value="理科" ' + (s.category === "理科" ? "selected" : "") + '>理科（2024）</option><option value="文科" ' + (s.category === "文科" ? "selected" : "") + '>文科（2024）</option></select></div>' +
      '<div class="field"><label>批次</label><select name="batch"><option value="本科批" ' + (s.batch === "本科批" ? "selected" : "") + '>本科批</option><option value="专科批" ' + (s.batch === "专科批" ? "selected" : "") + '>专科批</option></select></div>' +
      "</div>"
    );
  }

  function readDim(form) {
    return {
      province: Store.student.province,
      year: Number(form.year.value),
      category: form.category.value,
      batch: form.batch.value,
    };
  }

  function toolScore2Rank() {
    UI.modal({
      title: "一分一段查询",
      body:
        dimFields() +
        '<div class="field" style="margin-top:12px"><label>高考分数</label>' +
        '<input name="score" type="number" value="' + (Store.student.score || 600) + '" /></div>' +
        '<div id="s2r-out" style="margin-top:16px"></div>',
      footer: '<button class="btn js-cancel">关闭</button><button class="btn btn-primary js-ok">查询位次</button>',
      onMount(mask, close) {
        mask.querySelector(".js-cancel").addEventListener("click", close);
        mask.querySelector(".js-ok").addEventListener("click", async () => {
          const form = mask.querySelector(".modal-body");
          try {
            const r = await API.scoreToRank(Object.assign(readDim(form), { score: Number(form.score.value) }));
            mask.querySelector("#s2r-out").innerHTML =
              '<div class="rank-preview"><div><span class="sub">对应位次</span><br><b>' +
              UI.fmt.num(r.rank) + "</b></div>" +
              "<div><span class=\"sub\">分数段</span><br><b>" + UI.escapeHtml(r.rank_range || "-") + "</b></div>" +
              "<div><span class=\"sub\">本段人数</span><br><b>" + UI.fmt.num(r.segment_count) + "</b></div>" +
              "<div><span class=\"sub\">省控线</span><br><b>" + UI.fmt.score(r.control_score) + "</b></div></div>";
          } catch (e) {
            UI.toast(e.message, "error");
          }
        });
      },
    });
  }

  function toolRank2Score() {
    UI.modal({
      title: "位次反查分数",
      body:
        dimFields() +
        '<div class="field" style="margin-top:12px"><label>位次</label>' +
        '<input name="rank" type="number" value="' + (Store.student.rank || 30000) + '" /></div>' +
        '<div id="r2s-out" style="margin-top:16px"></div>',
      footer: '<button class="btn js-cancel">关闭</button><button class="btn btn-primary js-ok">查询分数</button>',
      onMount(mask, close) {
        mask.querySelector(".js-cancel").addEventListener("click", close);
        mask.querySelector(".js-ok").addEventListener("click", async () => {
          const form = mask.querySelector(".modal-body");
          try {
            const r = await API.rankToScore(Object.assign(readDim(form), { rank: Number(form.rank.value) }));
            mask.querySelector("#r2s-out").innerHTML =
              '<div class="rank-preview"><div><span class="sub">对应分数</span><br><b>' +
              UI.fmt.score(r.score) + "</b></div>" +
              "<div><span class=\"sub\">分数段</span><br><b>" + UI.escapeHtml(r.rank_range || "-") + "</b></div>" +
              "<div><span class=\"sub\">省控线</span><br><b>" + UI.fmt.score(r.control_score) + "</b></div></div>";
          } catch (e) {
            UI.toast(e.message, "error");
          }
        });
      },
    });
  }

  async function toolControl() {
    const s = Store.student;
    try {
      const r = await API.scoreToRank({ province: s.province, year: s.year, category: s.category, batch: s.batch, score: s.score || 500 });
      UI.modal({
        title: "省控线 · " + s.province + " " + s.year + " " + s.category,
        body:
          '<div class="rank-preview"><div><span class="sub">' + UI.escapeHtml(s.batch) + ' 省控线</span><br><b>' +
          UI.fmt.score(r.control_score) + "</b></div>" +
          "<div><span class=\"sub\">你的分数</span><br><b>" + UI.fmt.score(s.score) + "</b></div>" +
          "<div><span class=\"sub\">线差</span><br><b>+" + (s.score - r.control_score) + "</b></div></div>" +
          '<p class="sub" style="margin-top:14px">数据来自 score_range_' + s.year + "_henan 一分一段表。</p>",
      });
    } catch (e) {
      UI.toast(e.message, "error");
    }
  }

  async function toolTable() {
    UI.modal({
      title: "一分一段表",
      wide: true,
      body: UI.loadingHtml(),
      onMount(mask) {
        API.scoreTable(dims())
          .then((data) => {
            const rows = data.items || [];
            const s = Store.student;
            mask.querySelector(".modal-body").innerHTML =
              '<div class="table-wrap" style="max-height:60vh;overflow:auto"><table class="data">' +
              "<thead><tr><th>分数</th><th>分数段</th><th>本段人数</th><th>累计人数（位次）</th><th>位次区间</th></tr></thead><tbody>" +
              rows
                .map(
                  (r) =>
                    "<tr" + (r.score === Number(s.score) ? ' style="background:#eef2ff;font-weight:600"' : "") + "><td>" +
                    UI.fmt.score(r.score) + "</td><td>" + UI.escapeHtml(r.score_range || "-") +
                    "</td><td>" + UI.fmt.num(r.segment_count) + "</td><td>" + UI.fmt.num(r.cumulative_count) +
                    "</td><td>" + UI.escapeHtml(r.rank_range || "-") + "</td></tr>"
                )
                .join("") +
              "</tbody></table></div>";
          })
          .catch((e) => {
            mask.querySelector(".modal-body").innerHTML = UI.emptyHtml(e.message);
          });
      },
    });
  }

  return { render };
})();
