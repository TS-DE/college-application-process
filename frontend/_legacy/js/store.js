/* 全局状态：考生信息 + 我的志愿表（本地持久化） */
window.Store = (function () {
  const KEY_STU = "gk_student";
  const KEY_BOOK = "gk_book";

  const defaults = {
    province: "河南",
    grade: "高三",
    year: 2025,
    first_subject: "物理",
    subjects: [],
    level: null,
    category: "物理类",
    batch: "本科批",
    score: null,
    rank: null,
    control_score: null,
    name: "",
  };

  let student = Object.assign({}, defaults);
  let book = [];

  try {
    const s = JSON.parse(localStorage.getItem(KEY_STU) || "null");
    if (s) student = Object.assign(student, s);
  } catch (e) {
    /* 忽略损坏的本地数据 */
  }
  try {
    book = JSON.parse(localStorage.getItem(KEY_BOOK) || "[]");
  } catch (e) {
    book = [];
  }

  function saveStudent() {
    localStorage.setItem(KEY_STU, JSON.stringify(student));
    renderChip();
  }
  function saveBook() {
    localStorage.setItem(KEY_BOOK, JSON.stringify(book));
    renderBook();
  }

  function renderChip() {
    const main = document.getElementById("chip-main");
    const sub = document.getElementById("chip-sub");
    if (!main) return;
    if (student.score) {
      main.textContent = student.province + " · " + student.category + " · " + student.score + "分";
      sub.textContent = "位次 " + (student.rank ? Number(student.rank).toLocaleString("zh-CN") : "未换算") + " · " + student.batch;
    } else {
      main.textContent = "设置考生信息";
      sub.textContent = "点击填写分数与科类";
    }
  }

  function renderBook() {
    const list = document.getElementById("book-list");
    if (!list) return;
    const panel = document.getElementById("book-panel");
    const count = document.getElementById("book-count");
    const mini = document.getElementById("book-count-mini");
    if (count) count.textContent = book.length;
    if (mini) mini.textContent = book.length + " 条";
    if (!book.length) {
      if (panel) panel.classList.remove("show");
      list.innerHTML = '<div class="empty" style="padding:18px">还没有加入志愿，点击推荐卡片上的「加入志愿表」</div>';
      return;
    }
    if (panel) panel.classList.add("show");
    list.innerHTML = book
      .map(
        (it, i) =>
          '<div class="book-item"><span class="tier-chip tier-' +
          it.tier +
          '">' +
          UI.escapeHtml(it.tier_label) +
          '</span><span class="name">' +
          UI.escapeHtml(it.university_name) +
          " · " +
          UI.escapeHtml(it.major_name) +
          '</span><button class="icon-btn js-del" data-i="' +
          i +
          '">×</button></div>'
      )
      .join("");
    list.querySelectorAll(".js-del").forEach((btn) => {
      btn.addEventListener("click", () => {
        book.splice(Number(btn.dataset.i), 1);
        saveBook();
      });
    });
  }

  function inBook(item) {
    return book.some(
      (b) => b.university_name === item.university_name && b.major_name === item.major_name && b.major_group === item.major_group
    );
  }

  function addBook(item) {
    if (inBook(item)) {
      UI.toast("该志愿已在志愿表中", "warn");
      return false;
    }
    book.push({
      university_name: item.university_name,
      major_name: item.major_name,
      major_group: item.major_group,
      min_score: item.min_score,
      min_rank: item.min_rank,
      tier: item.tier,
      tier_label: item.tier_label,
      probability: item.probability,
    });
    saveBook();
    UI.toast("已加入我的志愿表", "success");
    return true;
  }

  function categoryFor(year, first) {
    return Number(year) >= 2025
      ? first + "类"
      : first === "物理"
      ? "理科"
      : "文科";
  }

  return {
    get student() {
      return student;
    },
    set(patch) {
      student = Object.assign({}, student, patch);
      if (patch.first_subject !== undefined || patch.year !== undefined) {
        student.category = categoryFor(student.year, student.first_subject);
      }
      if (patch.batch) {
        student.level = patch.batch === "本科批" ? "ben" : "zhuan";
      }
      if (!Array.isArray(student.subjects)) student.subjects = [];
      saveStudent();
    },
    get book() {
      return book;
    },
    addBook,
    inBook,
    refreshChip: renderChip,
    refreshBook: renderBook,
    clearBook() {
      book = [];
      saveBook();
    },
  };
})();
