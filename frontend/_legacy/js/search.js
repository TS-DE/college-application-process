/* 查大学 / 查专业 */
window.Search = (function () {
  const PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
  ];

  let state = { page: 1, page_size: 20, total: 0 };

  function template() {
    const s = Store.student;
    return (
      '<div class="panel">' +
      "<h3>查大学 / 专业</h3>" +
      '<p class="desc">所有查询都带省份、年份、科类、批次四个维度，物理隔离不串科。</p>' +
      '<div class="filter-bar">' +
      '<div class="field"><label>年份</label><select id="q-year">' +
      '<option value="2025"' + (s.year == 2025 ? " selected" : "") + ">2025</option>" +
      '<option value="2024"' + (s.year == 2024 ? " selected" : "") + ">2024</option>" +
      "</select></div>" +
      '<div class="field"><label>科类</label><select id="q-category">' +
      '<option value="物理类"' + (s.category === "物理类" || s.category === "理科" ? " selected" : "") + ">物理类 / 理科</option>" +
      '<option value="历史类"' + (s.category === "历史类" || s.category === "文科" ? " selected" : "") + ">历史类 / 文科</option>" +
      "</select></div>" +
      '<div class="field"><label>批次</label><select id="q-batch"><option value="本科批">本科批</option><option value="专科批">专科批</option></select></div>' +
      '<div class="field"><label>院校名称</label><input id="q-keyword" placeholder="如 郑州大学" value="' + UI.escapeHtml(window.__searchKeyword || "") + '" /></div>' +
      '<div class="field"><label>所属地区</label><select id="q-prov"><option value="">不限</option>' +
      PROVINCES.map((p) => '<option value="' + p + '">' + p + "</option>").join("") +
      "</select></div>" +
      '<div class="field"><label>办学类型</label><select id="q-nature"><option value="">不限</option><option value="公办">公办</option><option value="民办">民办</option></select></div>' +
      '<div class="field"><label>院校特色</label><select id="q-feature"><option value="">不限</option><option value="985">985</option><option value="211">211</option><option value="both">985 或 211</option></select></div>' +
      '<div class="field"><label>&nbsp;</label><button class="btn btn-primary" id="q-search">查询</button></div>' +
      "</div>" +
      '<div class="table-wrap"><div id="uni-box">' + UI.loadingHtml() + "</div></div>" +
      "</div>"
    );
  }

  function params() {
    const s = Store.student;
    const feature = document.getElementById("q-feature").value;
    return {
      province: s.province,
      year: Number(document.getElementById("q-year").value),
      category: document.getElementById("q-category").value,
      batch: document.getElementById("q-batch").value,
      keyword: document.getElementById("q-keyword").value.trim() || undefined,
      school_province: document.getElementById("q-prov").value || undefined,
      school_nature: document.getElementById("q-nature").value || undefined,
      is_985: feature === "985" ? true : undefined,
      is_211: feature === "211" || feature === "both" ? true : undefined,
      rank: s.rank || undefined,
      page: state.page,
      page_size: state.page_size,
    };
  }

  async function load() {
    const box = document.getElementById("uni-box");
    box.innerHTML = UI.loadingHtml();
    try {
      const data = await API.universities(params());
      state.total = data.total;
      if (!data.items.length) {
        box.innerHTML = UI.emptyHtml("没有匹配的院校，试试放宽条件");
        return;
      }
      box.innerHTML =
        '<table class="data"><thead><tr>' +
        "<th>院校名称</th><th>代码</th><th>地区</th><th>性质</th><th>特色</th>" +
        "<th>最低分</th><th>最低位次</th><th>位次差</th><th>推荐概率</th><th>操作</th>" +
        "</tr></thead><tbody>" +
        data.items.map(row).join("") +
        "</tbody></table>" +
        pager();
      bindRows(data.items);
      bindPager();
    } catch (e) {
      box.innerHTML = UI.emptyHtml(e.message);
    }
  }

  function row(s) {
    return (
      "<tr><td><b>" + UI.escapeHtml(s.university_name) + "</b></td>" +
      "<td>" + UI.escapeHtml(s.university_code || "-") + "</td>" +
      "<td>" + UI.escapeHtml(s.school_province || "-") + "</td>" +
      "<td>" + UI.escapeHtml(s.school_nature || "-") + "</td>" +
      "<td>" + UI.schoolTags(s) + "</td>" +
      "<td>" + UI.fmt.score(s.min_score) + "</td>" +
      "<td>" + UI.fmt.num(s.min_rank) + "</td>" +
      "<td>" + UI.fmt.diff(s.rank_diff) + "</td>" +
      "<td>" + (s.probability ? '<span class="tier-chip tier-' + s.tier + '">' + s.tier_label + "</span> " + s.probability + "%" : "-") + "</td>" +
      '<td><span class="link-cell js-majors" data-u="' + UI.escapeHtml(s.university_name) + '">查看专业</span></td></tr>'
    );
  }

  function pager() {
    const pages = Math.max(1, Math.ceil(state.total / state.page_size));
    return (
      '<div class="pager"><button class="btn btn-sm js-prev"' + (state.page <= 1 ? " disabled" : "") + ">上一页</button>" +
      "<span>第 " + state.page + " / " + pages + " 页 · 共 " + state.total + " 所</span>" +
      '<button class="btn btn-sm js-next"' + (state.page >= pages ? " disabled" : "") + ">下一页</button></div>"
    );
  }

  function bindPager() {
    document.querySelector(".js-prev").addEventListener("click", () => {
      if (state.page > 1) { state.page--; load(); }
    });
    document.querySelector(".js-next").addEventListener("click", () => {
      state.page++;
      load();
    });
  }

  function bindRows(items) {
    document.querySelectorAll(".js-majors").forEach((el) => {
      el.addEventListener("click", () => showMajors(el.dataset.u));
    });
  }

  function showMajors(name) {
    UI.modal({
      title: name + " · 专业录取明细",
      wide: true,
      body: UI.loadingHtml(),
      onMount(mask) {
        const s = Store.student;
        API.majors({
          province: s.province,
          year: Number(document.getElementById("q-year").value),
          category: document.getElementById("q-category").value,
          batch: document.getElementById("q-batch").value,
          university_name: name,
          page_size: 100,
        })
          .then((data) => {
            mask.querySelector(".modal-body").innerHTML =
              '<div class="table-wrap" style="max-height:60vh;overflow:auto"><table class="data"><thead><tr>' +
              "<th>专业</th><th>专业组</th><th>备注</th><th>选科要求</th><th>最低分</th><th>最低位次</th><th>录取/计划</th><th>学费</th>" +
              "</tr></thead><tbody>" +
              (data.items || [])
                .map(
                  (m) =>
                    "<tr><td><b>" + UI.escapeHtml(m.major_name || "-") + "</b></td>" +
                    "<td>" + UI.escapeHtml(m.major_group || "-") + "</td>" +
                    "<td>" + UI.escapeHtml(m.major_note || "-") + "</td>" +
                    "<td>" + UI.escapeHtml(m.subject_req || "-") + "</td>" +
                    "<td>" + UI.fmt.score(m.min_score) + "</td>" +
                    "<td>" + UI.fmt.num(m.min_rank) + "</td>" +
                    "<td>" + UI.fmt.num(m.admit_count || m.plan_count) + "</td>" +
                    "<td>" + UI.fmt.money(m.tuition) + "</td></tr>"
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

  function render(container) {
    state.page = 1;
    container.innerHTML = template();
    document.getElementById("q-search").addEventListener("click", () => {
      state.page = 1;
      load();
    });
    document.getElementById("q-keyword").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { state.page = 1; load(); }
    });
    window.__searchKeyword = "";
    load();
  }

  return { render };
})();
