/* 3+1+2 考生信息表单（右上角「考生信息」与「志愿填报·第一步」共用） */
window.ProfileForm = (function () {
  const GRADES = ["高三", "高二", "高一", "复读"];
  const SUBJECTS = [
    { key: "物理", label: "物 理", type: "first" },
    { key: "化学", label: "化 学", type: "second" },
    { key: "生物", label: "生 物", type: "second" },
    { key: "政治", label: "政 治", type: "second" },
    { key: "历史", label: "历 史", type: "first" },
    { key: "地理", label: "地 理", type: "second" },
  ];
  const YEARS = [2025, 2024];
  const BATCHES = ["本科批", "专科批"];

  function categoryOf(year, first) {
    if (!first) return null;
    return Number(year) >= 2025
      ? first + "类"
      : first === "物理"
      ? "理科"
      : "文科";
  }

  function esc(s) {
    return UI.escapeHtml(s);
  }

  /**
   * @param {HTMLElement} container
   * @param {{values?:Object, emptyScore?:boolean, onChange?:Function}} opts
   *   emptyScore=true（志愿填报页）时，分数 / 位次 / 批次一律留空，由用户自己填写
   */
  function render(container, opts) {
    const o = opts || {};
    const v = o.values || {};
    const emptyScore = !!o.emptyScore;

    const state = {
      province: v.province || "河南",
      grade: v.grade || "高三",
      year: Number(v.year || 2025),
      examType: "普通类",
      subjects: (v.subjects || []).slice(),
      firstSubject: v.first_subject || null,
      level: emptyScore ? null : v.level || null,
      score: emptyScore ? "" : v.score != null ? String(v.score) : "",
      rank: emptyScore ? "" : v.rank != null ? String(v.rank) : "",
      batch: emptyScore ? "" : v.batch || "",
      batchAuto: false,
      manualRank: false,
      lines: [],
      bounds: {},
      minLine: null,
      fullScore: 750,
    };

    // 兼容旧数据：把 first_subject 也加入 subjects 列表统一展示
    if (state.firstSubject && state.subjects.indexOf(state.firstSubject) < 0) {
      state.subjects.unshift(state.firstSubject);
    }
    if (state.subjects.length > 3) state.subjects = state.subjects.slice(0, 3);

    container.innerHTML =
      '<div class="pform">' +
      '<div class="exam-type-tabs">' +
      '<div class="exam-tab on" data-v="普通类"><b>普通类</b><span>文化科目</span></div>' +
      '<div class="exam-tab disabled" data-v="艺术类"><b>艺术类</b><span>后续支持</span></div>' +
      "</div>" +

      '<div class="pform-row">' +
      '<div class="field"><label>考试地区</label><select data-k="province">' +
      '<option value="河南">河南</option></select></div>' +
      '<div class="field"><label>所属年级</label><select data-k="grade">' +
      GRADES.map((g) => '<option value="' + g + '"' + (state.grade === g ? " selected" : "") + ">" + g + "</option>").join("") +
      "</select></div></div>" +

      '<div class="pform-row">' +
      '<div class="field"><label>参考年份</label><select data-k="year">' +
      YEARS.map(
        (y) =>
          '<option value="' + y + '"' + (state.year === y ? " selected" : "") + ">" +
          y + (y >= 2025 ? "（新高考）" : "（老高考）") + "</option>"
      ).join("") +
      "</select></div>" +
      '<div class="field"><label>成绩类型</label>' +
      '<div class="radio-group" data-k="level">' +
      '<label><input type="radio" name="level" value="ben"' +
      (state.level === "ben" ? ' checked' : '') +
      '><span>本科</span></label>' +
      '<label><input type="radio" name="level" value="zhuan"' +
      (state.level === "zhuan" ? ' checked' : '') +
      '><span>专科</span></label>' +
      "</div></div></div>" +

      '<div class="pform-row single"><div class="field"><label>高考科目（3 + 1 + 2）</label>' +
      '<div class="pill-group" data-k="subject">' +
      SUBJECTS.map(
        (s) =>
          '<button type="button" class="pill' + (state.subjects.indexOf(s.key) >= 0 ? " on" : "") +
          '" data-v="' + s.key + '">' + s.label + "</button>"
      ).join("") +
      "</div><span class=\"hint\">请选择首选科目（物理/历史）及最多 2 门再选科目</span></div></div>" +

      '<div class="pform-row">' +
      '<div class="field"><label>预估分数</label>' +
      '<div class="input-unit" data-k="score-box"><input data-k="score" type="number" inputmode="numeric" ' +
      'placeholder="请输入分数" value="' + esc(state.score) + '" /><span class="unit">分</span></div>' +
      '<span class="field-error" data-k="score-err"></span></div>' +
      '<div class="field"><label>对应位次</label>' +
      '<div class="input-unit"><input data-k="rank" type="number" inputmode="numeric" ' +
      'placeholder="请输入对应排名" value="' + esc(state.rank) + '" /><span class="unit">名</span></div>' +
      '<span class="hint">填入分数后自动换算，可手动修改</span></div>' +
      "</div>" +

      '<div class="pform-row single"><div class="field batch-field"><label>填报批次</label>' +
      '<div class="batch-wrap"><select data-k="batch"><option value="">请完善信息</option>' +
      BATCHES.map((b) => '<option value="' + b + '"' + (state.batch === b ? " selected" : "") + ">" + b + "</option>").join("") +
      "</select><span class=\"batch-tag\" data-k=\"batch-tag\" style=\"display:none\">推荐</span></div></div></div>" +

      '<div class="rank-preview" data-k="preview" style="display:none"></div>' +
      "</div>";

    const $ = (k) => container.querySelector('[data-k="' + k + '"]');

    /* ---------------- 渲染辅助 ---------------- */
    function paintSubjects() {
      const firstSel = state.subjects.filter((k) => k === "物理" || k === "历史");
      const full = state.subjects.length >= 3;
      container.querySelectorAll('[data-k="subject"] .pill').forEach((b) => {
        const k = b.dataset.v;
        const on = state.subjects.indexOf(k) >= 0;
        let disabled = false;
        if (!on) {
          if (full) disabled = true;
          // 物理/历史 互斥
          if ((k === "物理" && state.subjects.indexOf("历史") >= 0) ||
              (k === "历史" && state.subjects.indexOf("物理") >= 0)) {
            disabled = true;
          }
        }
        b.classList.toggle("on", on);
        b.classList.toggle("disabled", disabled);
      });
    }

    function paintLevel() {
      container.querySelectorAll('[name="level"]').forEach((r) => {
        r.checked = r.value === state.level;
      });
    }

    function updateScoreHint() {
      const box = $("score");
      const b = state.level ? state.bounds[state.level] : null;
      if (b && b.max >= b.min) {
        box.placeholder = "请输入分数" + b.min + "-" + b.max;
      } else {
        box.placeholder = "请输入分数1-" + state.fullScore;
      }
    }

    function paintPreview(d) {
      const box = $("preview");
      if (!d || !d.rank) {
        box.style.display = "none";
        box.innerHTML = "";
        return;
      }
      box.style.display = "block";
      box.innerHTML =
        "分数对应" +
        '<span class="year-mark">' + esc(String(state.year)) + "年</span> 排名区间为" +
        '<span class="rank-mark">' + esc(d.rank_range || "-") + "名</span>，可手动输入";
    }

    function clearConverted() {
      state.rank = "";
      state.batch = "";
      state.batchAuto = false;
      $("rank").value = "";
      $("batch").value = "";
      $("batch-tag").style.display = "none";
      paintPreview(null);
    }

    /* ---------------- 数据加载 ---------------- */
    async function refreshLines() {
      try {
        const first = getFirstSubject();
        const d = await API.controlLines({
          province: state.province,
          year: state.year,
          category: categoryOf(state.year, first) || "物理类",
        });
        state.lines = d.lines || [];
        state.bounds = d.bounds || {};
        state.minLine = d.min_line;
        state.fullScore = d.full_score || 750;
      } catch (e) {
        state.lines = [];
        state.bounds = {};
        state.minLine = null;
      }
      updateScoreHint();
    }

    /* ---------------- 温馨提示（未过任何批次线） ---------------- */
    function warnBelowLine(d) {
      const rows = (d.lines || [])
        .map(
          (l) =>
            '<div class="warn-line"><b>' + esc(l.batch) + "</b>" +
            "<span>高考批次线：" + UI.fmt.score(l.control_score) + "分</span></div>"
        )
        .join("");
      UI.modal({
        title: "温馨提示",
        body:
          '<p style="text-align:center;margin:4px 0 10px">您的<span class="warn-head">高考成绩(' +
          Math.round(Number(d.score)) + "分)</span> 没过本省最低批次线，建议检查分数输入是否正确</p>" +
          rows,
        footer: '<button class="btn btn-primary js-ok" style="width:100%">知道了</button>',
        onMount(mask, close) {
          mask.querySelector(".js-ok").addEventListener("click", close);
        },
      });
    }

    /* ---------------- 自动换算 ---------------- */
    let checkSeq = 0;

    function showError(msg) {
      $("score-box").classList.add("err");
      $("score-err").textContent = msg;
    }

    function clearError() {
      $("score-box").classList.remove("err");
      $("score-err").textContent = "";
    }

    function scoreInLevelRange(n) {
      const b = state.level ? state.bounds[state.level] : null;
      if (!b) return true;
      return n >= b.min && n <= b.max;
    }

    async function autoCheck(silent) {
      const seq = ++checkSeq;
      const raw = $("score").value;
      clearError();
      if (raw === "") {
        clearConverted();
        notify();
        return;
      }
      const n = Number(raw);
      if (!Number.isFinite(n) || !Number.isInteger(n) || n < 1 || n > state.fullScore) {
        showError("请输入 1 - " + state.fullScore + " 之间的整数分数");
        clearConverted();
        notify();
        return;
      }
      if (state.level && !scoreInLevelRange(n)) {
        const b = state.bounds[state.level];
        const typeName = state.level === "ben" ? "本科" : "专科";
        showError(typeName + "成绩类型可填写 " + b.min + " - " + b.max + " 分");
        clearConverted();
        notify();
        return;
      }

      try {
        const d = await API.scoreCheck({
          province: state.province,
          year: state.year,
          category: categoryOf(state.year, getFirstSubject()) || "物理类",
          score: n,
        });
        if (seq !== checkSeq) return;

        if (d.below_all) {
          clearConverted();
          warnBelowLine(d);
          notify();
          return;
        }

        state.batch = d.recommend_batch || "";
        state.batchAuto = true;
        $("batch").value = state.batch;
        $("batch-tag").style.display = state.batchAuto ? "inline-flex" : "none";
        if (!state.manualRank) {
          state.rank = String(d.rank);
          $("rank").value = state.rank;
        }
        paintPreview(d);
      } catch (e) {
        if (seq === checkSeq) UI.toast(e.message, "error");
      }
      notify();
    }

    async function reconvertByBatch() {
      const raw = $("score").value;
      if (raw === "" || !state.batch) return;
      const n = Number(raw);
      if (!Number.isFinite(n)) return;
      if (state.level && !scoreInLevelRange(n)) return;
      try {
        const d = await API.scoreToRank({
          province: state.province,
          year: state.year,
          category: categoryOf(state.year, getFirstSubject()) || "物理类",
          batch: state.batch,
          score: n,
        });
        state.rank = String(d.rank);
        state.manualRank = false;
        $("rank").value = state.rank;
        paintPreview(d);
      } catch (e) {
        UI.toast(e.message, "error");
      }
      notify();
    }

    function notify() {
      if (o.onChange) o.onChange(get());
    }

    function getFirstSubject() {
      if (state.subjects.indexOf("物理") >= 0) return "物理";
      if (state.subjects.indexOf("历史") >= 0) return "历史";
      return null;
    }

    /* ---------------- 事件绑定 ---------------- */
    container.querySelectorAll('[data-k="subject"] .pill').forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.v;
        const i = state.subjects.indexOf(key);
        if (i >= 0) {
          state.subjects.splice(i, 1);
        } else {
          if (state.subjects.length >= 3) {
            UI.toast("高考科目最多选择 3 门", "warn");
            return;
          }
          state.subjects.push(key);
        }
        paintSubjects();
        state.manualRank = false;
        refreshLines().then(() => autoCheck(true));
      });
    });

    container.querySelectorAll('[name="level"]').forEach((r) => {
      r.addEventListener("change", () => {
        state.level = r.value;
        state.manualRank = false;
        updateScoreHint();
        autoCheck(true);
      });
    });

    ["province", "grade"].forEach((k) => {
      $(k).addEventListener("change", () => {
        state[k] = $(k).value;
        if (k === "province") {
          state.manualRank = false;
          clearConverted();
          refreshLines().then(() => autoCheck(true));
        }
        notify();
      });
    });

    $("year").addEventListener("change", () => setYear($("year").value));

    let timer = null;
    $("score").addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => autoCheck(false), 450);
    });
    $("score").addEventListener("blur", () => autoCheck(false));

    $("rank").addEventListener("input", () => {
      state.manualRank = $("rank").value !== "";
      state.rank = $("rank").value;
      notify();
    });

    $("batch").addEventListener("change", () => {
      state.batch = $("batch").value;
      state.batchAuto = false;
      $("batch-tag").style.display = "none";
      if (!state.batch) return;
      state.level = state.batch === "本科批" ? "ben" : "zhuan";
      paintLevel();
      updateScoreHint();
      reconvertByBatch();
    });

    container.querySelectorAll(".exam-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        if (tab.classList.contains("disabled")) {
          UI.toast("暂只支持普通类，艺术类后续补充", "info");
          return;
        }
        container.querySelectorAll(".exam-tab").forEach((t) => t.classList.remove("on"));
        tab.classList.add("on");
        state.examType = tab.dataset.v;
        notify();
      });
    });

    function setYear(y) {
      state.year = Number(y);
      $("year").value = String(state.year);
      state.manualRank = false;
      clearConverted();
      refreshLines().then(() => autoCheck(true));
    }

    async function init() {
      await refreshLines();
      paintSubjects();
      if (state.score !== "") autoCheck(true);
      else notify();
    }

    function get() {
      const first = getFirstSubject();
      const second = state.subjects.filter((k) => k !== first);
      return {
        province: state.province,
        grade: state.grade,
        year: state.year,
        examType: state.examType,
        first_subject: first,
        subjects: second,
        category: categoryOf(state.year, first),
        level: state.level,
        score: $("score").value === "" ? null : Number($("score").value),
        rank: $("rank").value === "" ? null : Number($("rank").value),
        batch: state.batch || null,
      };
    }

    function validate() {
      const g = get();
      if (!g.first_subject) return { ok: false, message: "请选择首选科目（物理或历史）" };
      if (g.subjects.length > 2) return { ok: false, message: "再选科目最多选择 2 门" };
      if (!g.score) return { ok: false, message: "请先填写预估分数" };
      if (!g.rank) return { ok: false, message: "请先填写分数以换算位次，或手动填写对应位次" };
      if (!g.batch) return { ok: false, message: "请选择填报批次（填入分数后会自动推荐）" };
      return { ok: true, value: g };
    }

    paintLevel();
    updateScoreHint();

    return { get, validate, init, setYear, refreshLines, getState: () => state };
  }

  return { render, categoryOf };
})();
