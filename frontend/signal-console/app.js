/* ============================================================
   WEIBO SIGNAL · AI 讨论信号观测台
   全部数据运行时从后端接口获取，不固化任何业务数据。
   接口（相对 /data/）：trend-ai · sentiment · hot-today · hot-yesterday
   设计要点：
   - 每个数据源独立状态机（loading / ok / pending / error），互不连坐
   - 请求超时、防乱序（每源独立序号）、手动刷新防连点、自动刷新静默不打断
   - 所有时间统一固定北京时间（UTC+8），不随用户浏览器时区漂移
   - 近 7 天趋势按北京自然日补齐缺失日，KPI 与波形同口径
   - 情感比率归一化填满，样本数取真实分析条数 total_analyzed
   - 首屏加载骨架、错误态可重试、完整键盘无障碍
   ============================================================ */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var DATA = '/data/';
  var FETCH_TIMEOUT = 15000;

  /* ---------------- 状态（每个数据源独立） ---------------- */
  function srcState() { return { status: 'loading', data: null, win: null, seq: 0, rendered: false }; }
  var state = {
    mode: 'today',
    today: srcState(),
    yesterday: srcState(),
    trend: srcState(),
    sentiment: srcState()
  };

  /* ---------------- 基础工具 ---------------- */
  function $(id) { return document.getElementById(id); }
  function num(n) { return (n === null || n === undefined || isNaN(n)) ? '–' : Number(n).toLocaleString('zh-CN'); }
  function pad2(x) { return String(x).padStart(2, '0'); }
  function shortDate(d) { d = String(d); return d.length >= 10 ? d.slice(5, 10) : d; }

  /* 固定北京时间（UTC+8），不随用户浏览器时区漂移 */
  function bjUtc(ms) { return new Date(ms + 8 * 3600 * 1000); }
  function bjHM(ms) { var b = bjUtc(ms); return pad2(b.getUTCHours()) + ':' + pad2(b.getUTCMinutes()); }
  function ymdKey(y, m, d) { return y + '-' + pad2(m) + '-' + pad2(d); }
  function shiftYMD(y, m, d, delta) {
    var b = new Date(Date.UTC(y, m - 1, d) + delta * 86400000);
    return [b.getUTCFullYear(), b.getUTCMonth() + 1, b.getUTCDate()];
  }
  function bjTodayYMD() {
    var b = bjUtc(Date.now());
    return [b.getUTCFullYear(), b.getUTCMonth() + 1, b.getUTCDate()];
  }
  /* 后端 publish_time 是“北京墙上时刻”的 naive 字符串（无时区），直接按字符串读，
     不经过 new Date() 的时区转换，避免海外/非北京时区机器上日期偏移 */
  function fmtNaive(s) {
    var m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    return m ? (m[2] + '-' + m[3] + ' ' + m[4] + ':' + m[5]) : '';
  }

  /* ---------------- 数据获取（带超时） ---------------- */
  function fetchJSON(path) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, FETCH_TIMEOUT);
    return fetch(DATA + path, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: ctrl.signal
    }).then(function (res) {
      if (res.status === 503) {
        return res.json().catch(function () { return null; }).then(function (body) {
          throw { status: 503, body: body };
        });
      }
      if (!res.ok) { throw { status: res.status }; }
      return res.json();
    }).finally(function () { clearTimeout(timer); });
  }

  /* ---------------- 近 7 天趋势窗口（按北京自然日补齐缺失日） ---------------- */
  function buildTrendWindow(trend) {
    var map = {};
    (((trend || {}).daily_trend) || []).forEach(function (x) {
      var key = String((x && x.date) || '').slice(0, 10);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return;
      map[key] = { post: Number(x.post_count) || 0, comment: Number(x.comment_count) || 0 };
    });
    var t = bjTodayYMD();
    var days = [];
    for (var i = 6; i >= 0; i--) {
      var p = shiftYMD(t[0], t[1], t[2], -i);
      var key = ymdKey(p[0], p[1], p[2]);
      var v = map[key] || { post: 0, comment: 0 };
      days.push({ date: key, post: v.post, comment: v.comment, total: v.post + v.comment });
    }
    var total = days.reduce(function (a, d) { return a + d.total; }, 0);
    return { days: days, total: total };
  }

  /* ---------------- 情感比率归一化（三段合计恒为 100，避免留缝/溢出） ---------------- */
  function normRatios(s) {
    function ratio(k) { var v = Number(s[k]); return isFinite(v) ? Math.max(0, Math.min(100, v)) : 0; }
    var p = ratio('positive_ratio'), u = ratio('neutral_ratio'), n = ratio('negative_ratio');
    var sum = p + u + n;
    var analyzed = Number(s.total_analyzed) || 0;
    if (sum <= 0 || analyzed <= 0) {
      return { empty: true, p: 0, u: 0, n: 0, rawP: 0, rawU: 0, rawN: 0 };
    }
    return { empty: false, p: p / sum, u: u / sum, n: n / sum, rawP: p, rawU: u, rawN: n };
  }

  /* ---------------- 数字动画 ---------------- */
  function tween(el, apply, dur) {
    if (el.__raf) cancelAnimationFrame(el.__raf);
    if (el.__to) clearTimeout(el.__to);
    if (reduceMotion) { apply(1); return; }
    var start = null;
    function step(ts) {
      if (!start) start = ts;
      var t = Math.min((ts - start) / dur, 1);
      apply(1 - Math.pow(1 - t, 3));
      if (t < 1) el.__raf = requestAnimationFrame(step);
    }
    el.__raf = requestAnimationFrame(step);
    el.__to = setTimeout(function () {
      if (el.__raf) cancelAnimationFrame(el.__raf);
      el.__raf = null;
      apply(1);
    }, dur + 150);
  }
  function countUp(el, target, dur) {
    if (target === null || target === undefined || isNaN(target)) { el.textContent = '–'; return; }
    target = Number(target);
    if (reduceMotion) { el.textContent = target.toLocaleString('zh-CN'); return; }
    tween(el, function (e) { el.textContent = Math.round(target * e).toLocaleString('zh-CN'); }, dur);
  }
  function ratioUp(el, target, dur) {
    if (target === null || target === undefined || isNaN(target)) { el.textContent = '–'; return; }
    target = Number(target);
    if (reduceMotion) { el.textContent = target.toFixed(1) + '%'; return; }
    tween(el, function (e) { el.textContent = (target * e).toFixed(1) + '%'; }, dur);
  }

  /* ---------------- 加载 / 错误 / 骨架 ---------------- */
  function iconRetry() {
    return '<svg class="state-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11A8 8 0 0 0 6.3 6.3L4 8.5M4 4v4.5H8.5M4 13a8 8 0 0 0 13.7 4.7L20 15.5M20 20v-4.5H15.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }
  function makeRetryButton(onRetry) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn-retry';
    b.textContent = '重试';
    b.addEventListener('click', onRetry);
    return b;
  }
  function errorNode(onRetry) {
    var d = document.createElement('div');
    d.className = 'state-box state-error';
    d.innerHTML = iconRetry();
    var p = document.createElement('p'); p.textContent = '暂时无法获取该时段数据';
    var small = document.createElement('small'); small.textContent = '网络或服务异常，点击右侧按钮重试';
    d.appendChild(p); d.appendChild(small); d.appendChild(makeRetryButton(onRetry));
    return d;
  }
  function emptyNode(kind) {
    var d = document.createElement('div');
    d.className = 'state-box state-empty' + (kind === 'pending' ? ' state-pending' : '');
    var mark = '<svg class="state-ic" viewBox="0 0 40 40" fill="none" aria-hidden="true" style="width:42px;height:42px;"><path d="M3 23h5l3-10 4 15 4-19 4 14h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var map = {
      pending: ['昨日数据补采进行中', '通常北京时间 08:30 后完成，稍后切换「昨日全日」查看'],
      'today-empty': ['今日信号采集中', '第一条 AI 相关讨论出现后，将在此实时呈现'],
      other: ['当前时段暂无符合条件的 AI 行业讨论', '热点经 AI 相关性筛选，宁精勿滥']
    };
    var m = map[kind] || map.other;
    d.innerHTML = mark + '<p></p><small></small>';
    d.querySelector('p').textContent = m[0];
    d.querySelector('small').textContent = m[1];
    return d;
  }
  function skeletonBlock() {
    var f = document.createDocumentFragment();
    for (var i = 0; i < 4; i++) {
      var d = document.createElement('div');
      d.className = 'wire-item skeleton';
      d.setAttribute('aria-hidden', 'true');
      d.innerHTML = '<div class="wire-rank sk"></div><div class="wire-main">' +
        '<div class="sk sk-line w55"></div><div class="sk sk-line w100"></div>' +
        '<div class="sk sk-line w40"></div></div>';
      f.appendChild(d);
    }
    return f;
  }
  function setOverlay(id, status, onRetry) {
    var el = $(id);
    if (!el) return;
    el.innerHTML = '';
    if (status === 'ok') { el.hidden = true; return; }
    el.hidden = false;
    var inner = document.createElement('div');
    inner.className = 'overlay-inner';
    if (status === 'loading') {
      inner.innerHTML = '<span class="spinner" aria-hidden="true"></span><p class="ov-text">数据加载中…</p>';
    } else {
      var p = document.createElement('p');
      p.className = 'ov-text ov-error';
      p.textContent = '数据加载失败';
      inner.appendChild(p);
      inner.appendChild(makeRetryButton(onRetry));
    }
    el.appendChild(inner);
  }

  /* ---------------- 关键读数 ---------------- */
  function renderReadouts() {
    var st = state[state.mode];
    var n = (st.status === 'ok' && st.data) ? ((st.data.data || []).length) : null;
    countUp($('post-count'), n, 900);
    $('count-label').textContent = state.mode === 'today' ? '今日相关讨论' : '昨日相关讨论';
    var note = $('count-note');
    if (state.mode === 'today') {
      note.textContent = st.status === 'loading' ? '加载中…' : '今日 00:00 起 · 持续更新';
    } else if (st.status === 'pending') {
      note.textContent = '昨日补采中 · 稍后定稿';
    } else if (st.status === 'loading') {
      note.textContent = '昨日数据加载中';
    } else if (st.status === 'error') {
      note.textContent = '暂时无法获取';
    } else {
      note.textContent = '昨日全日 · 已定稿';
    }

    var tt = state.trend;
    if (tt.status === 'ok' && tt.win) countUp($('mention-count'), tt.win.total, 1200);
    else $('mention-count').textContent = '–';

    var ss = state.sentiment;
    if (ss.status === 'ok' && ss.data) {
      var analyzed = Number(ss.data.total_analyzed) || 0;
      ratioUp($('positive-ratio'), analyzed > 0 ? Number(ss.data.positive_ratio) : null, 1000);
      countUp($('sample-size'), analyzed > 0 ? analyzed : null, 900);
    } else {
      $('positive-ratio').textContent = '–';
      $('sample-size').textContent = '–';
    }
  }

  /* ---------------- 情感仪表 + 负面频谱 ---------------- */
  function renderSentiment() {
    var st = state.sentiment;
    renderReadouts();
    if (st.status === 'loading' && !st.data) { setOverlay('sent-overlay', 'loading'); return; }
    if (st.status === 'error' && !st.data) { setOverlay('sent-overlay', 'error', function () { loadSentiment(); }); return; }
    if (!st.data) return;
    setOverlay('sent-overlay', 'ok');
    var s = st.data;
    var analyzed = Number(s.total_analyzed) || 0;
    var nr = normRatios(s);
    var pos = $('gauge-pos'), neu = $('gauge-neu'), neg = $('gauge-neg');
    if (nr.empty) {
      pos.style.flexGrow = 0; neu.style.flexGrow = 0; neg.style.flexGrow = 1;
      pos.style.opacity = 0; neu.style.opacity = 0; neg.style.opacity = 0.18;
      $('sent-pos').textContent = '–'; $('sent-neu').textContent = '–'; $('sent-neg').textContent = '–';
      $('sent-sample-tag').textContent = '暂无样本';
      renderNegSpectrum([]);
      return;
    }
    pos.style.opacity = 1; neu.style.opacity = 1; neg.style.opacity = 1;
    pos.style.flexGrow = nr.p; neu.style.flexGrow = nr.u; neg.style.flexGrow = nr.n;
    $('sent-pos').textContent = nr.rawP.toFixed(1) + '%';
    $('sent-neu').textContent = nr.rawU.toFixed(1) + '%';
    $('sent-neg').textContent = nr.rawN.toFixed(1) + '%';
    $('sent-sample-tag').textContent = '抽样 ' + num(analyzed);
    renderNegSpectrum(s.top_negative_viewpoints || []);
  }
  function renderNegSpectrum(list) {
    var box = $('neg-spectrum');
    box.innerHTML = '';
    list = (list || []).slice(0, 10);
    if (!list.length) {
      var p = document.createElement('p');
      p.className = 'spectrum-empty';
      p.textContent = '暂无负面观点词样本';
      box.appendChild(p);
      return;
    }
    var max = list.reduce(function (a, b) { return Math.max(a, b.count || 0); }, 1);
    list.forEach(function (item, i) {
      var row = document.createElement('div');
      row.className = 'spec-row';
      row.innerHTML = '<span class="spec-word"></span><span class="spec-track"><span class="spec-fill"></span></span><span class="spec-count"></span>';
      row.querySelector('.spec-word').textContent = item.word;
      row.querySelector('.spec-count').textContent = item.count;
      box.appendChild(row);
      var w = ((item.count || 0) / max) * 100;
      setTimeout(function () { row.querySelector('.spec-fill').style.width = w + '%'; }, 120 + i * 55);
    });
  }

  /* ---------------- 热点电讯 ---------------- */
  function validUrl(u) { return typeof u === 'string' && /^https:\/\/m\.weibo\.cn\/detail\/\d+$/.test(u); }
  function emptyNode2(kind) { return emptyNode(kind); }
  function wireItem(p, i, maxScore, instant) {
    var a = document.createElement('a');
    a.className = 'wire-item' + (instant ? ' is-in' : '');
    var ok = validUrl(p.url);
    a.href = ok ? p.url : '#';
    if (ok) { a.target = '_blank'; a.rel = 'noopener'; }
    else { a.addEventListener('click', function (e) { e.preventDefault(); }); }

    var rank = document.createElement('div');
    rank.className = 'wire-rank';
    rank.textContent = pad2(i + 1);

    var main = document.createElement('div');
    main.className = 'wire-main';

    var top = document.createElement('div');
    top.className = 'wire-top';
    var author = document.createElement('span');
    author.className = 'wire-author';
    author.textContent = '@' + (p.username || '未知');
    top.appendChild(author);
    if (p.category) {
      var cat = document.createElement('span');
      cat.className = 'wire-cat';
      cat.textContent = p.category;
      top.appendChild(cat);
    }

    var content = document.createElement('p');
    content.className = 'wire-content';
    content.textContent = p.content || '';

    var foot = document.createElement('div');
    foot.className = 'wire-foot';
    var score = Math.round(p.hotspot_score || 0);
    var scoreEl = document.createElement('span');
    scoreEl.className = 'wire-score';
    scoreEl.innerHTML = '<span class="wire-heat"><i></i></span>热度 ' + score;
    scoreEl.querySelector('.wire-heat i').style.width = Math.max(7, (score / maxScore) * 100) + '%';
    foot.appendChild(scoreEl);

    var tmText = fmtNaive(p.publish_time);
    if (!tmText && typeof p.publish_timestamp === 'number') {
      var b = bjUtc(p.publish_timestamp);
      tmText = pad2(b.getUTCMonth() + 1) + '-' + pad2(b.getUTCDate()) + ' ' + pad2(b.getUTCHours()) + ':' + pad2(b.getUTCMinutes());
    }
    if (tmText) {
      var tm = document.createElement('span');
      tm.className = 'wire-time';
      tm.textContent = tmText;
      foot.appendChild(tm);
    }
    var go = document.createElement('span');
    go.className = 'wire-go';
    go.textContent = '查看原博 →';
    foot.appendChild(go);

    main.appendChild(top);
    main.appendChild(content);
    main.appendChild(foot);
    a.appendChild(rank);
    a.appendChild(main);
    if (!instant) setTimeout(function () { a.classList.add('is-in'); }, 90 + i * 70);
    return a;
  }
  function renderPosts() {
    var mode = state.mode;
    var st = state[mode];
    var box = $('posts');
    $('posts-label').textContent = mode === 'today' ? '今日 · 按热度排序' : '昨日全日 · 按热度排序';
    box.innerHTML = '';

    if (st.status === 'loading') { $('posts-count-tag').textContent = '加载中'; box.appendChild(skeletonBlock()); return; }
    if (st.status === 'pending') { $('posts-count-tag').textContent = '补采中'; box.appendChild(emptyNode('pending')); return; }
    if (st.status === 'error' || !st.data) {
      $('posts-count-tag').textContent = '— 条';
      box.appendChild(errorNode(function () { loadHot(mode); }));
      return;
    }
    var list = st.data.data || [];
    $('posts-count-tag').textContent = list.length + ' 条';
    if (!list.length) { box.appendChild(emptyNode(mode === 'today' ? 'today-empty' : 'other')); return; }

    var maxScore = list.reduce(function (a, b) { return Math.max(a, b.hotspot_score || 0); }, 1);
    var instant = st.rendered;
    list.forEach(function (p, i) { box.appendChild(wireItem(p, i, maxScore, instant)); });
    st.rendered = true;
  }

  /* ---------------- 数据截至时间 / 徽章（固定北京时间） ---------------- */
  function asOfMs(st) {
    var h = st.data;
    if (!h) return null;
    if (h.data_as_of) {
      var ms = Date.parse(h.data_as_of);
      if (!isNaN(ms)) return ms;
    }
    var latest = null;
    (h.data || []).forEach(function (p) {
      if (typeof p.publish_timestamp === 'number' && (latest === null || p.publish_timestamp > latest)) {
        latest = p.publish_timestamp;
      }
    });
    return latest;
  }
  function stampUpdated() {
    var st = state[state.mode];
    var u = $('updated');
    if (st.status === 'loading') { u.textContent = '加载中…'; return; }
    if (st.status === 'pending') { u.textContent = '昨日补采中…'; return; }
    if (st.status === 'error' || !st.data) { u.textContent = '数据时间未知'; return; }
    var ms = asOfMs(st);
    if (ms === null) { u.textContent = '数据时间未知'; return; }
    var hm = bjHM(ms);
    u.textContent = state.mode === 'today' ? '数据截至 ' + hm : '昨日 ' + hm + ' 定稿';
  }
  function renderBadge() {
    var isYesterday = state.mode === 'yesterday';
    var badge = $('live-badge');
    badge.classList.toggle('is-final', isYesterday);
    badge.querySelector('.live-text').textContent = isYesterday ? '昨日定稿' : '观测中';
  }
  function renderHot() {
    renderPosts();
    renderReadouts();
    stampUpdated();
    renderBadge();
  }

  /* ---------------- 签名：AI 信号波形（canvas） ---------------- */
  function smoothPath(ctx, pts) {
    ctx.moveTo(pts[0].x, pts[0].y);
    for (var i = 0; i < pts.length - 1; i++) {
      var xc = (pts[i].x + pts[i + 1].x) / 2, yc = (pts[i].y + pts[i + 1].y) / 2;
      ctx.quadraticCurveTo(pts[i].x, pts[i].y, xc, yc);
    }
    ctx.lineTo(pts[pts.length - 1].x, pts[pts.length - 1].y);
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  var wave = {
    canvas: $('wave'),
    ctx: null,
    dpr: 1, w: 0, h: 0,
    days: [], maxV: 1, zeroMax: false, primed: false,
    hover: null, scan: 0, reveal: 0, t: 0, raf: null,
    pad: { l: 46, r: 14, t: 26, b: 30 },
    teal: '#34E8B0', amber: '#F2B45E',

    setup: function (win) {
      var days = (win && win.days) || [];
      this.days = days;
      this.maxV = Math.max.apply(null, days.map(function (d) { return d.total; }).concat([1]));
      this.zeroMax = days.length > 0 && days.every(function (d) { return d.total === 0; });
      this.ctx = this.canvas.getContext('2d');
      if (!this.primed) this.reveal = reduceMotion ? 1 : 0;
      else this.reveal = 1;
      this.resize();
      this.updateReadout();
      if (!this.primed && !reduceMotion && !this.raf) this.animate();
      this.primed = true;
    },
    resize: function () {
      var rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.canvas.width = Math.round(rect.width * this.dpr);
      this.canvas.height = Math.round(rect.height * this.dpr);
      this.w = rect.width; this.h = rect.height;
      this.draw();
    },
    peakIdx: function () {
      var p = 0;
      for (var i = 1; i < this.days.length; i++) {
        if (this.days[i].total > this.days[p].total) p = i;
      }
      return p;
    },
    updateReadout: function () {
      if (!this.days.length) return;
      var isHover = this.hover !== null;
      var idx = isHover ? this.hover : this.peakIdx();
      var d = this.days[idx];
      $('wr-day').textContent = shortDate(d.date) + (isHover ? '' : (this.zeroMax ? ' · 暂无' : ' · 峰值'));
      $('wr-post').textContent = num(d.post);
      $('wr-comment').textContent = num(d.comment);
      $('wr-total').textContent = num(d.total);
    },
    bind: function () {
      var self = this;
      function idxFromEvent(e) {
        var rect = self.canvas.getBoundingClientRect();
        var point = e.touches ? e.touches[0] : e;
        var cx = point.clientX - rect.left;
        var n = self.days.length;
        if (n <= 1) return 0;
        var span = (self.w - self.pad.r) - self.pad.l;
        var frac = (cx - self.pad.l) / span;
        return Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1))));
      }
      this.canvas.addEventListener('mousemove', function (e) {
        self.hover = idxFromEvent(e); self.updateReadout(); self.draw();
      });
      this.canvas.addEventListener('mouseleave', function () {
        self.hover = null; self.updateReadout(); self.draw();
      });
      this.canvas.addEventListener('touchstart', function (e) {
        self.hover = idxFromEvent(e); self.updateReadout(); self.draw();
      }, { passive: true });
      this.canvas.addEventListener('touchmove', function (e) {
        self.hover = idxFromEvent(e); self.updateReadout(); self.draw();
      }, { passive: true });
      window.addEventListener('resize', function () { self.resize(); });
    },
    animate: function () {
      var self = this, last = performance.now();
      function loop(now) {
        var dt = (now - last) / 1000; last = now;
        if (self.reveal < 1) self.reveal = Math.min(1, self.reveal + dt / 1.2);
        self.scan = (self.scan + dt / 7.5) % 1;
        self.t = now / 1000;
        self.draw();
        self.raf = requestAnimationFrame(loop);
      }
      this.raf = requestAnimationFrame(loop);
    },
    draw: function () {
      var ctx = this.ctx;
      if (!ctx) return;
      var self = this;
      ctx.save();
      ctx.scale(this.dpr, this.dpr);
      ctx.clearRect(0, 0, this.w, this.h);

      var p = this.pad, x0 = p.l, x1 = this.w - p.r, y0 = p.t, y1 = this.h - p.b;
      var n = this.days.length;

      if (!n) {
        ctx.fillStyle = 'rgba(95,117,107,.9)';
        ctx.font = "13px 'Noto Sans SC',sans-serif";
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText('等待信号数据接入…', (x0 + x1) / 2, (y0 + y1) / 2);
        ctx.restore();
        return;
      }

      var maxV = this.maxV;
      function X(i) { return x0 + (n <= 1 ? (x1 - x0) / 2 : (x1 - x0) * i / (n - 1)); }
      function Y(v) { return y1 - (v / maxV) * (y1 - y0) * 0.82; }

      ctx.font = "10px 'IBM Plex Mono',monospace";
      ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      for (var k = 0; k <= 4; k++) {
        var gy = y1 - (k / 4) * (y1 - y0) * 0.82;
        ctx.strokeStyle = 'rgba(140,210,180,.09)';
        ctx.lineWidth = 1;
        ctx.setLineDash(k === 0 ? [] : [3, 5]);
        ctx.beginPath(); ctx.moveTo(x0, gy); ctx.lineTo(x1, gy); ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(95,117,107,.9)';
        if (this.zeroMax) ctx.fillText(k === 0 ? '0' : '', 6, gy);
        else ctx.fillText(String(Math.round(maxV * k / 4)), 6, gy);
      }

      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillStyle = 'rgba(95,117,107,.95)';
      for (var i2 = 0; i2 < n; i2++) {
        ctx.fillText(shortDate(this.days[i2].date), X(i2), y1 + 11);
      }

      var postPts = this.days.map(function (d, i) { return { x: X(i), y: Y(d.post) }; });
      var cmtPts = this.days.map(function (d, i) { return { x: X(i), y: Y(d.comment) }; });
      var clipX = x0 + this.reveal * (x1 - x0);

      ctx.save();
      ctx.beginPath();
      ctx.rect(x0, y0 - 12, Math.max(0, clipX - x0), (y1 - y0) + 24);
      ctx.clip();

      var grad = ctx.createLinearGradient(0, y0, 0, y1);
      grad.addColorStop(0, 'rgba(52,232,176,.30)');
      grad.addColorStop(1, 'rgba(52,232,176,.01)');
      ctx.beginPath();
      ctx.moveTo(postPts[0].x, y1);
      postPts.forEach(function (pt) { ctx.lineTo(pt.x, pt.y); });
      ctx.lineTo(postPts[postPts.length - 1].x, y1);
      ctx.closePath();
      ctx.fillStyle = grad; ctx.fill();

      ctx.beginPath(); smoothPath(ctx, postPts);
      ctx.strokeStyle = this.teal; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();

      ctx.beginPath(); smoothPath(ctx, cmtPts);
      ctx.strokeStyle = this.amber; ctx.lineWidth = 1.6; ctx.stroke();

      var tt = this.t;
      postPts.forEach(function (pt, i) {
        if (pt.x > clipX + 1) return;
        var br = 1 + (reduceMotion ? 0 : Math.sin(tt * 2 + i) * 0.12);
        ctx.beginPath(); ctx.arc(pt.x, pt.y, 3.2 * br, 0, Math.PI * 2);
        ctx.fillStyle = '#0A1210'; ctx.fill();
        ctx.beginPath(); ctx.arc(pt.x, pt.y, 3.2 * br, 0, Math.PI * 2);
        ctx.strokeStyle = self.teal; ctx.lineWidth = 1.6; ctx.stroke();
      });
      cmtPts.forEach(function (pt) {
        if (pt.x > clipX + 1) return;
        ctx.beginPath(); ctx.arc(pt.x, pt.y, 2.2, 0, Math.PI * 2);
        ctx.fillStyle = self.amber; ctx.fill();
      });
      ctx.restore();

      if (this.reveal >= 1 && !this.zeroMax) {
        var pi = this.peakIdx(), pd = this.days[pi];
        var px = X(pi), py = Y(pd.total);
        ctx.strokeStyle = 'rgba(242,180,94,.4)'; ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.moveTo(px, py - 7); ctx.lineTo(px, py - 19); ctx.stroke();
        ctx.setLineDash([]);
        var label = '峰值 ' + pd.total;
        ctx.font = "600 10px 'IBM Plex Mono',monospace";
        var tw = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(242,180,94,.15)';
        roundRect(ctx, px - tw / 2 - 6, py - 32, tw + 12, 17, 3); ctx.fill();
        ctx.fillStyle = self.amber; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(label, px, py - 23.5);
      }

      if (this.reveal >= 1 && this.hover !== null) {
        var hx = X(this.hover);
        ctx.strokeStyle = 'rgba(52,232,176,.55)'; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(hx, y0 - 6); ctx.lineTo(hx, y1); ctx.stroke();
        ctx.setLineDash([]);
        [[postPts[this.hover], this.teal], [cmtPts[this.hover], this.amber]].forEach(function (a) {
          ctx.beginPath(); ctx.arc(a[0].x, a[0].y, 6, 0, Math.PI * 2);
          ctx.strokeStyle = a[1]; ctx.lineWidth = 1.4; ctx.stroke();
        });
      }

      if (this.reveal >= 1 && !reduceMotion) {
        var sx = x0 + this.scan * (x1 - x0);
        var sg = ctx.createLinearGradient(sx, y0, sx, y1);
        sg.addColorStop(0, 'rgba(52,232,176,0)');
        sg.addColorStop(.5, 'rgba(52,232,176,.5)');
        sg.addColorStop(1, 'rgba(52,232,176,0)');
        ctx.strokeStyle = sg; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(sx, y0 - 4); ctx.lineTo(sx, y1); ctx.stroke();
        ctx.beginPath(); ctx.arc(sx, y0 - 7, 1.8, 0, Math.PI * 2);
        ctx.fillStyle = self.teal; ctx.fill();
      }

      ctx.restore();
    }
  };
  wave.bind();

  /* ---------------- 各数据源加载（每源独立序号防乱序） ---------------- */
  function loadHot(mode, opts) {
    opts = opts || {};
    var st = state[mode], my = ++st.seq;
    if (!(opts.silent && st.data)) st.status = 'loading';
    renderHot();
    return fetchJSON(mode === 'today' ? 'hot-today' : 'hot-yesterday')
      .then(function (d) {
        if (my !== st.seq) return;
        st.data = d; st.status = 'ok';
        renderHot();
      })
      .catch(function (e) {
        if (my !== st.seq) return;
        st.status = (e && e.status === 503 && mode === 'yesterday') ? 'pending' : 'error';
        renderHot();
      });
  }
  function renderTrend() {
    var st = state.trend;
    if (st.win) {
      setOverlay('wave-overlay', 'ok');
      wave.setup(st.win);
    } else if (st.status === 'loading') {
      setOverlay('wave-overlay', 'loading');
    } else if (st.status === 'error') {
      setOverlay('wave-overlay', 'error', function () { loadTrend(); });
    }
    renderReadouts();
  }
  function loadTrend(opts) {
    opts = opts || {};
    var st = state.trend, my = ++st.seq;
    if (!(opts.silent && st.data)) st.status = 'loading';
    renderTrend();
    return fetchJSON('trend-ai')
      .then(function (d) {
        if (my !== st.seq) return;
        st.data = d; st.win = buildTrendWindow(d); st.status = 'ok';
        renderTrend();
      })
      .catch(function () {
        if (my !== st.seq) return;
        st.status = 'error'; renderTrend();
      });
  }
  function loadSentiment(opts) {
    opts = opts || {};
    var st = state.sentiment, my = ++st.seq;
    if (!(opts.silent && st.data)) st.status = 'loading';
    renderSentiment();
    return fetchJSON('sentiment')
      .then(function (d) {
        if (my !== st.seq) return;
        st.data = d; st.status = 'ok'; renderSentiment();
      })
      .catch(function () {
        if (my !== st.seq) return;
        st.status = 'error'; renderSentiment();
      });
  }

  function loadAll(silent) {
    var o = { silent: !!silent };
    return Promise.allSettled([
      loadTrend(o),
      loadSentiment(o),
      loadHot('today', o),
      loadHot('yesterday', o)
    ]).then(function () {
      stampUpdated();
      renderBadge();
    });
  }

  /* ---------------- 今日 / 昨日切换（含键盘无障碍） ---------------- */
  var TAB_ORDER = ['today', 'yesterday'];
  function updateTabs(mode, focus) {
    TAB_ORDER.forEach(function (m) {
      var btn = $('tab-' + m);
      var active = m === mode;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
      btn.tabIndex = active ? 0 : -1;
    });
    var panel = $('panel-posts');
    if (panel) panel.setAttribute('aria-labelledby', 'tab-' + mode);
    if (focus) { var b = $('tab-' + mode); if (b && b.focus) b.focus(); }
  }
  function selectMode(mode) {
    state.mode = mode;
    updateTabs(mode, false);
    renderHot();
  }
  $('tab-today').addEventListener('click', function () { selectMode('today'); });
  $('tab-yesterday').addEventListener('click', function () { selectMode('yesterday'); });
  $('tablist').addEventListener('keydown', function (e) {
    var i = TAB_ORDER.indexOf(state.mode);
    var next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { next = TAB_ORDER[(i + 1) % TAB_ORDER.length]; }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { next = TAB_ORDER[(i - 1 + TAB_ORDER.length) % TAB_ORDER.length]; }
    else if (e.key === 'Home') { next = TAB_ORDER[0]; }
    else if (e.key === 'End') { next = TAB_ORDER[TAB_ORDER.length - 1]; }
    if (next) { e.preventDefault(); selectMode(next); updateTabs(next, true); }
  });

  /* ---------------- 手动刷新（防连点） ---------------- */
  function manualRefresh() {
    var btn = $('btn-refresh');
    if (btn.disabled) return Promise.resolve();
    btn.disabled = true;
    btn.classList.add('is-loading');
    btn.setAttribute('aria-busy', 'true');
    return loadAll(false).then(function () {
      btn.disabled = false;
      btn.classList.remove('is-loading');
      btn.setAttribute('aria-busy', 'false');
    });
  }
  $('btn-refresh').addEventListener('click', manualRefresh);

  /* 15 分钟静默自动刷新（保留已有数据，不打断阅读） */
  setInterval(function () { loadAll(true); }, 15 * 60 * 1000);

  /* ---------------- 面板滚动揭示 ---------------- */
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
    });
  }, { threshold: 0.1 });
  document.querySelectorAll('.panel').forEach(function (pnl) {
    pnl.classList.add('reveal');
    io.observe(pnl);
  });

  /* ---------------- 顶部时钟（固定北京时间） ---------------- */
  function tickClock() {
    var b = bjUtc(Date.now());
    $('clock').textContent = pad2(b.getUTCHours()) + ':' + pad2(b.getUTCMinutes()) + ':' + pad2(b.getUTCSeconds());
  }

  /* ---------------- 初始化 ---------------- */
  tickClock();
  setInterval(tickClock, 1000);
  updateTabs('today', false);
  // 首屏先渲染一次加载骨架/占位
  renderHot();
  renderTrend();
  renderSentiment();
  loadAll(false);
  // 首屏渲染繁忙兜底
  setTimeout(function () { renderReadouts(); renderBadge(); }, 1500);
})();
