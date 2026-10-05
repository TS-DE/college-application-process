/* 后端接口封装（同源部署，直接用相对路径 /api） */
window.API = (function () {
  async function request(path, options) {
    const opts = options || {};
    const url = new URL(path, location.origin);
    if (opts.params) {
      Object.keys(opts.params).forEach((k) => {
        const v = opts.params[k];
        if (v !== undefined && v !== null && v !== "") {
          url.searchParams.append(k, v);
        }
      });
    }
    const init = { method: opts.method || "GET", headers: {} };
    if (opts.body) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let res;
    try {
      res = await fetch(url.toString(), init);
    } catch (e) {
      throw new Error("无法连接后端服务，请确认已启动：python main.py");
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = j.detail || detail;
      } catch (e) {
        /* 非 JSON 错误 */
      }
      throw new Error(detail);
    }
    return res.json();
  }

  const get = (path, params) => request("/api" + path, { params });
  const post = (path, body) => request("/api" + path, { method: "POST", body });

  return {
    get,
    post,
    health: () => get("/health"),
    aiStatus: () => get("/ai/status"),

    options: (province) => get("/meta/options", { province }),
    provinceStats: (p) => get("/meta/province-stats", p),
    hotSchools: (p) => get("/meta/hot-schools", p),
    scoreTable: (p) => get("/meta/score-table", p),
    controlLines: (p) => get("/meta/control-lines", p),
    scoreCheck: (p) => get("/meta/score-check", p),

    scoreToRank: (p) => get("/score-to-rank", p),
    rankToScore: (p) => get("/rank-to-score", p),
    profile: (body) => post("/student/profile", body),

    recommend: (body) => post("/recommend", body),
    aiReasons: (body) => post("/recommend/ai-reasons", body),

    universities: (p) => get("/universities", p),
    majors: (p) => get("/majors", p),

    parseIntent: (body) => post("/ai/parse-intent", body),
    reason: (body) => post("/ai/recommend-reason", body),
    chat: (body) => post("/ai/chat", body),
  };
})();
