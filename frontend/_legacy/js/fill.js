/* 志愿填报：分步表单 + 冲稳保结果 */
window.Fill = (function () {
  let filters = {};
  let parsed = null;
  let busy = false;
  let form = null;

  const INTERESTS = [
    "计算机/人工智能", "电子信息", "电气/自动化", "机械/车辆", "土木/建筑",
    "医学/临床", "药学/护理", "师范/教育", "金融/经济", "会计/审计",
    "法学/公安", "语言/传媒", "数学/统计", "化学/材料", "生物/农学",
    "设计/艺术", "工商管理", "留在省内", "去北上广", "学费要便宜", "只要公办",
  ];

  function template() {
    return (
      '<div class="steps">' +
      '<div class="step active" data-step="1"><span class="step-no">1</span>高考信息</div>' +
      '<div class="step-line"></div>' +
      '<div class="step" data-step="2"><span class="step-no">2</span>兴趣与偏好</div>' +
      '<div class="step-line"></div>' +
      '<div class="step" data-step="3"><span class="step-no">3</span>生成志愿表</div>' +
      "</div>" +

      /* ---------- Step 1 ---------- */
      '<div class="panel" id="panel-1">' +
      "<h3>第一步 · 高考信息</h3>" +
      '<p class="desc">采用 3+1+2 模式：填入预估分数后系统自动换算并推荐填报批次，结果均可手动修改。</p>' +
      '<div id="profile-form"></div>' +
      '<div style="margin-top:18px;display:flex;gap:10px;align-items:center">' +
      '<button class="btn btn-primary js-next">下一步：填兴趣偏好</button>' +
      "</div>" +
      "</div>" +

      /* ---------- Step 2 ---------- */
      '<div class="panel" id="panel-2">' +
      "<h3>第二步 · 兴趣与偏好（可选）</h3>" +
      '<p class="desc">直接说一句话让 AI 帮你解析，或者点选下面的标签。</p>' +
      '<div class="interest-tags" id="interest-tags">' +
      INTERESTS.map((t) => '<button class="interest-tag" data-t="' + t + '">' + t + "</button>").join("") +
      "</div>" +
      '<div class="ai-input-row">' +
      '<input id="f-ai-text" placeholder="例如：我想找个离家近、计算机强、学费便宜的公办学校" />' +
      '<button class="btn btn-primary js-parse">AI 解析</button>' +
      "</div>" +
      '<div id="parsed-box"></div>' +
      '<div style="margin-top:18px">' +
      '<button class="btn btn-primary btn-lg js-generate">智能选志愿</button>' +
      "</div>" +
      "</div>" +

      '<div id="panel-3"></div>'
    );
  }

  function render(container) {
    container.innerHTML = template();
    // 每次进入志愿填报，分数 / 位次 / 批次 / 选科一律留空，由用户重新填写
    form = ProfileForm.render(document.getElementById("profile-form"), {
      values: {
        province: Store.student.province,
        grade: Store.student.grade,
        year: Store.student.year,
      },
      emptyScore: true,
      onChange: () => {},
    });
    form.init();
    bind(container);

    // 从顶部搜索框跳转过来时，回填 AI 解析出的筛选条件
    if (window.__prefillFilters) {
      parsed = window.__prefillFilters;
      window.__prefillFilters = null;
      if (window.__prefillText) {
        document.getElementById("f-ai-text").value = window.__prefillText;
        window.__prefillText = null;
      }
      renderParsed();
      setStep(2);
      setTimeout(() => document.getElementById("panel-2").scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    }
  }

  function bind(container) {
    container.querySelector(".js-next").addEventListener("click", () => {
      const v = form.validate();
      if (!v.ok) return UI.toast(v.message, "warn");
      Store.set(v.value);
      setStep(2);
      document.getElementById("panel-2").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    container.querySelectorAll(".interest-tag").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.classList.toggle("on");
        applyTags();
      });
    });

    container.querySelector(".js-parse").addEventListener("click", async () => {
      const text = document.getElementById("f-ai-text").value.trim();
      if (!text) return UI.toast("请先输入你的想法", "warn");
      const btn = container.querySelector(".js-parse");
      btn.disabled = true;
      btn.textContent = "解析中…";
      try {
        parsed = await API.parseIntent({ text: text, province: Store.student.province });
        renderParsed();
      } catch (e) {
        UI.toast(e.message, "error");
      } finally {
        btn.disabled = false;
        btn.textContent = "AI 解析";
      }
    });

    container.querySelector(".js-generate").addEventListener("click", generate);
  }

  function setStep(n) {
    document.querySelectorAll(".step").forEach((el) => {
      const s = Number(el.dataset.step);
      el.classList.toggle("active", s === n);
      el.classList.toggle("done", s < n);
    });
  }

  function applyTags() {
    const on = Array.from(document.querySelectorAll(".interest-tag.on")).map((b) => b.dataset.t);
    filters = {};
    const majorMap = {
      "计算机/人工智能": "计算机", "电子信息": "电子信息", "电气/自动化": "自动化",
      "机械/车辆": "机械", "土木/建筑": "土木", "医学/临床": "临床",
      "药学/护理": "药学", "师范/教育": "师范", "金融/经济": "金融",
      "会计/审计": "会计", "法学/公安": "法学", "语言/传媒": "外语",
      "数学/统计": "数学", "化学/材料": "化学", "生物/农学": "生物",
      "设计/艺术": "设计", "工商管理": "工商管理",
    };
    on.forEach((t) => {
      if (majorMap[t]) filters.major_keyword = majorMap[t];
      if (t === "留在省内") filters.school_province = Store.student.province;
      if (t === "去北上广") filters.school_province = "北京";
      if (t === "学费要便宜") filters.tuition_max = 6000;
      if (t === "只要公办") filters.school_nature = "公办";
    });
    renderParsed();
  }

  function renderParsed() {
    const box = document.getElementById("parsed-box");
    if (!box) return;
    const f = parsed ? Object.assign({}, filters, stripEmpty(parsed)) : filters;
    const keys = Object.keys(f).filter((k) => k !== "source" && k !== "raw");
    if (!keys.length) {
      box.innerHTML = "";
      return;
    }
    const label = {
      major_keyword: "专业方向", exclude_keyword: "排除", school_province: "院校省份",
      tuition_max: "学费上限", school_nature: "办学性质", is_985: "985", is_211: "211",
      region_preference: "地域偏好", subject_req: "选科要求",
    };
    box.innerHTML =
      '<div class="parsed-filters"><b>当前筛选条件</b>' +
      (parsed ? '<span class="src">（来源：' + (parsed.source === "llm" ? "AI 解析" : "规则解析") + "）</span>" : "") +
      "<div style=\"margin-top:6px\">" +
      keys
        .map((k) => '<span class="tag tag-green">' + UI.escapeHtml(label[k] || k) + "：" + UI.escapeHtml(String(f[k])) + "</span>")
        .join("") +
      "</div></div>";
  }

  function stripEmpty(obj) {
    const out = {};
    Object.keys(obj).forEach((k) => {
      const v = obj[k];
      if (v !== null && v !== undefined && v !== "" && v !== false && k !== "raw") out[k] = v;
    });
    return out;
  }

  async function generate() {
    if (busy) return;
    const v = form.validate();
    if (!v.ok) {
      setStep(1);
      document.getElementById("panel-1").scrollIntoView({ behavior: "smooth", block: "start" });
      return UI.toast(v.message, "warn");
    }
    const f = v.value;
    busy = true;
    const btn = document.querySelector(".js-generate");
    btn.disabled = true;
    btn.textContent = "正在生成志愿表…";
    setStep(3);
    const panel = document.getElementById("panel-3");
    panel.innerHTML = '<div class="panel">' + UI.loadingHtml("规则引擎正在匹配院校专业…") + "</div>";
    panel.scrollIntoView({ behavior: "smooth", block: "start" });

    const extra = parsed ? stripEmpty(parsed) : {};
    if (f.subjects && f.subjects.length) extra.subject_selected = f.subjects;

    const payload = Object.assign({}, f, {
      filters: Object.assign({}, filters, extra),
      limit: 60,
      with_ai: false,
    });

    try {
      const data = await API.recommend(payload);
      Store.set(f);
      window.__lastResult = data;
      try {
        sessionStorage.setItem("gk_last_result", JSON.stringify(data));
      } catch (e) {
        /* 结果过大时忽略缓存 */
      }
      location.hash = "#/result";
    } catch (e) {
      panel.innerHTML = '<div class="panel">' + UI.emptyHtml(e.message) + "</div>";
    } finally {
      busy = false;
      btn.disabled = false;
      btn.textContent = "智能选志愿";
    }
  }

  return { render };
})();


/* ==================== 推荐结果页 ==================== */
window.ResultView = (function () {
  let current = "chong";

  function loadCache() {
    try {
      return JSON.parse(sessionStorage.getItem("gk_last_result") || "null");
    } catch (e) {
      return null;
    }
  }

  function render(container) {
    const data = window.__lastResult || loadCache();
    if (!data) {
      container.innerHTML =
        '<div class="card">' + UI.emptyHtml("还没有生成志愿表，请先到「志愿填报」填写信息") + "</div>";
      return;
    }
    const s = data.student;
    container.innerHTML =
      '<div class="result-head"><div><div class="who">' +
      UI.escapeHtml(s.province) + " · " + UI.escapeHtml(s.category) + " · " + UI.escapeHtml(s.batch) +
      "</div><div style=\"opacity:.8;font-size:13px;margin-top:4px\">" +
      (s.score ? "高考分数 " + s.score : "") +
      (s.control_score ? " ｜ 省控线 " + s.control_score : "") +
      (s.score && s.control_score ? " ｜ 线差 +" + (s.score - s.control_score) : "") +
      "</div></div>" +
      '<div class="nums">' +
      '<div><b>' + UI.fmt.num(s.rank) + "</b><span>你的位次</span></div>" +
      '<div><b>' + data.chong.length + "</b><span>冲</span></div>" +
      '<div><b>' + data.wen.length + "</b><span>稳</span></div>" +
      '<div><b>' + data.bao.length + "</b><span>保</span></div>" +
      "</div></div>" +

      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:10px">' +
      '<div class="tabs" id="tier-tabs">' +
      tabHtml("chong", "冲", data.chong.length) +
      tabHtml("wen", "稳", data.wen.length) +
      tabHtml("bao", "保", data.bao.length) +
      "</div>" +
      '<div style="display:flex;gap:8px">' +
      '<button class="btn btn-sm js-ai-batch">✨ AI 生成推荐理由</button>' +
      '<button class="btn btn-sm js-back">修改条件</button>' +
      "</div></div>" +
      '<div id="rec-list"></div>' +
      '<p class="sub" style="margin-top:16px">共扫描 ' + data.meta.total_scanned +
      " 条录取数据，耗时 " + data.meta.elapsed_ms + " ms；冲稳保按位次差 ±" + data.meta.buffer + " 划分。</p>";

    bind(container, data);
    renderList(data);
  }

  function tabHtml(key, label, n) {
    return (
      '<button class="tab' + (key === current ? " on" : "") + '" data-tier="' + key + '">' +
      label + '<span class="badge">' + n + "</span></button>"
    );
  }

  function bind(container, data) {
    container.querySelectorAll("#tier-tabs .tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        current = btn.dataset.tier;
        container.querySelectorAll("#tier-tabs .tab").forEach((b) => b.classList.toggle("on", b === btn));
        renderList(data);
      });
    });
    container.querySelector(".js-back").addEventListener("click", () => {
      location.hash = "#/fill";
    });
    container.querySelector(".js-ai-batch").addEventListener("click", async () => {
      const btn = container.querySelector(".js-ai-batch");
      btn.disabled = true;
      btn.textContent = "AI 正在撰写…";
      UI.toast("正在调用本地大模型，约需十几秒", "success");
      try {
        const picked = []
          .concat(data.chong.slice(0, 3), data.wen.slice(0, 4), data.bao.slice(0, 3))
          .map((it) => Object.assign({}, it));
        const res = await API.aiReasons({ student: data.student, items: picked, limit: 10 });
        const map = {};
        res.items.forEach((it) => {
          map[it.university_name + "|" + it.major_name + "|" + (it.major_group || "")] = it;
        });
        ["chong", "wen", "bao"].forEach((tier) => {
          data[tier].forEach((it) => {
            const hit = map[it.university_name + "|" + it.major_name + "|" + (it.major_group || "")];
            if (hit) {
              it.ai_reason = hit.ai_reason;
              it.ai = hit.ai;
            }
          });
        });
        UI.toast("已生成 " + res.generated + " 条 AI 理由", "success");
        renderList(data);
      } catch (e) {
        UI.toast(e.message, "error");
      } finally {
        btn.disabled = false;
        btn.textContent = "✨ AI 生成推荐理由";
      }
    });
  }

  function renderList(data) {
    const box = document.getElementById("rec-list");
    const items = data[current] || [];
    if (!items.length) {
      box.innerHTML = UI.emptyHtml("该档位暂无匹配结果，可放宽筛选条件试试");
      return;
    }
    box.innerHTML = items.map(cardHtml).join("");
    box.querySelectorAll(".js-add").forEach((btn) => {
      btn.addEventListener("click", () => {
        const it = items[Number(btn.dataset.i)];
        if (Store.addBook(it)) btn.textContent = "已加入";
      });
    });
    box.querySelectorAll(".js-detail").forEach((btn) => {
      btn.addEventListener("click", () => showDetail(items[Number(btn.dataset.i)]));
    });
    box.querySelectorAll(".js-ai").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const it = items[Number(btn.dataset.i)];
        btn.disabled = true;
        btn.textContent = "生成中…";
        try {
          const r = await API.reason({
            university_name: it.university_name,
            major_name: it.major_name,
            min_rank: it.min_rank,
            min_score: it.min_score,
            student_rank: data.student.rank,
            student_score: data.student.score,
            tier: it.tier,
            school_province: it.school_province,
            tuition: it.tuition,
          });
          it.ai_reason = r.reason;
          it.ai = r.source === "llm";
          renderList(data);
        } catch (e) {
          UI.toast(e.message, "error");
          btn.disabled = false;
          btn.textContent = "✨ AI 解读";
        }
      });
    });
  }

  function cardHtml(it, i) {
    const prob = it.probability || 0;
    const color = it.tier === "chong" ? "var(--chong)" : it.tier === "wen" ? "var(--wen)" : "var(--bao)";
    const reason = it.ai && it.ai_reason ? it.ai_reason : it.reason;
    return (
      '<div class="rec-card">' +
      '<div class="rec-main">' +
      "<h4>" + UI.escapeHtml(it.university_name) +
      '<span class="major">' + UI.escapeHtml(it.major_name || "") + "</span>" +
      '<span class="tier-chip tier-' + it.tier + '" style="margin-left:8px">' + it.tier_label + "</span></h4>" +
      "<div>" + UI.schoolTags(it) + "</div>" +
      '<div class="rec-info">' +
      "<span>最低分 <b>" + UI.fmt.score(it.min_score) + "</b></span>" +
      "<span>最低位次 <b>" + UI.fmt.num(it.min_rank) + "</b></span>" +
      "<span>位次差 <b>" + UI.fmt.diff(it.rank_diff) + "</b></span>" +
      (it.tuition ? "<span>学费 <b>" + UI.fmt.money(it.tuition) + "</b></span>" : "") +
      (it.plan_count ? "<span>计划 <b>" + UI.fmt.num(it.plan_count) + "</b> 人</span>" : "") +
      (it.subject_req ? "<span>选科 <b>" + UI.escapeHtml(it.subject_req) + "</b></span>" : "") +
      "</div>" +
      '<div class="rec-reason' + (it.ai ? " ai" : "") + '">' +
      (it.ai ? '<span class="ai-badge">AI</span>' : "") +
      UI.escapeHtml(reason || "") +
      "</div>" +
      "</div>" +
      '<div class="rec-side">' +
      '<div><div class="big" style="color:' + color + '">' + prob + "%</div>" +
      '<div class="rank">预估录取概率</div></div>' +
      '<div class="prob-bar"><i style="width:' + prob + "%;background:" + color + '"></i></div>' +
      '<div class="rec-actions">' +
      '<button class="btn btn-sm js-add" data-i="' + i + '">' +
      (Store.inBook(it) ? "已加入" : "加入志愿表") + "</button>" +
      '<button class="btn btn-sm js-detail" data-i="' + i + '">详情</button>' +
      '<button class="btn btn-sm js-ai" data-i="' + i + '">✨ AI 解读</button>' +
      "</div></div></div>"
    );
  }

  function showDetail(it) {
    UI.modal({
      title: UI.escapeHtml(it.university_name) + " · " + UI.escapeHtml(it.major_name || ""),
      wide: true,
      body: UI.loadingHtml(),
      onMount(mask) {
        const s = Store.student;
        API.majors({
          province: s.province,
          year: s.year,
          category: s.category,
          batch: s.batch,
          university_name: it.university_name,
          page_size: 60,
        })
          .then((data) => {
            mask.querySelector(".modal-body").innerHTML =
              '<div class="rank-preview" style="margin:0 0 16px">' +
              "<div><span class=\"sub\">最低分</span><br><b>" + UI.fmt.score(it.min_score) + "</b></div>" +
              "<div><span class=\"sub\">最低位次</span><br><b>" + UI.fmt.num(it.min_rank) + "</b></div>" +
              "<div><span class=\"sub\">位次差</span><br><b>" + UI.fmt.diff(it.rank_diff) + "</b></div>" +
              "<div><span class=\"sub\">预估概率</span><br><b>" + (it.probability || "-") + "%</b></div></div>" +
              (it.major_note ? '<p class="sub">专业备注：' + UI.escapeHtml(it.major_note) + "</p>" : "") +
              '<h4 style="margin:16px 0 8px">该院校其他专业（同科类同批次）</h4>' +
              '<div class="table-wrap" style="max-height:46vh;overflow:auto"><table class="data">' +
              "<thead><tr><th>专业</th><th>专业组</th><th>选科要求</th><th>最低分</th><th>最低位次</th><th>计划/录取</th><th>学费</th></tr></thead><tbody>" +
              (data.items || []).map(
                (m) =>
                  "<tr" + (m.major_name === it.major_name ? ' style="background:#eef2ff;font-weight:600"' : "") + "><td>" +
                  UI.escapeHtml(m.major_name || "-") + "</td><td>" + UI.escapeHtml(m.major_group || "-") +
                  "</td><td>" + UI.escapeHtml(m.subject_req || "-") + "</td><td>" + UI.fmt.score(m.min_score) +
                  "</td><td>" + UI.fmt.num(m.min_rank) + "</td><td>" + UI.fmt.num(m.plan_count || m.admit_count) +
                  "</td><td>" + UI.fmt.money(m.tuition) + "</td></tr>"
              ).join("") +
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
