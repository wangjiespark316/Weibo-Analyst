/* ============================================================
   WEIBO SIGNAL · AI 讨论信号观测台
   全部数据运行时从后端接口获取，不固化任何业务数据。
   接口（相对 /data/）：trend-ai · sentiment · hot-today · hot-yesterday
   ============================================================ */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var DATA = '/data/';

  var state = {
    mode: 'today',
    trend: null,
    sentiment: null,
    hot: { today: null, yesterday: null },
    status: { today: null, yesterday: null }
  };

  function $(id) { return document.getElementById(id); }
  function num(n) { return (n === null || n === undefined || isNaN(n)) ? '–' : Number(n).toLocaleString('zh-CN'); }
  function pad2(x) { return String(x).padStart(2, '0'); }
  function shortDate(d) { d = String(d); return d.length >= 10 ? d.slice(5, 10) : d; }

  /* ---------------- 数据获取 ---------------- */
  function fetchJSON(path) {
    return fetch(DATA + path, { headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(function (res) {
        if (res.status === 503) {
          return res.json().catch(function () { return null; }).then(function (body) {
            throw { status: 503, body: body };
          });
        }
        if (!res.ok) { throw { status: res.status }; }
        return res.json();
      });
  }

  function ensureHot(mode) {
    return fetchJSON(mode === 'today' ? 'hot-today' : 'hot-yesterday')
      .then(function (d) { state.hot[mode] = d; state.status[mode] = 'ok'; })
      .catch(function (e) {
        state.hot[mode] = null;
        state.status[mode] = (e && e.status === 503) ? 'pending' : 'error';
      })
      .then(function () { renderPosts(); renderReadouts(); });
  }

  /* ---------------- 时钟 / 更新时间 ---------------- */
  function tickClock() {
    var d = new Date();
    $('clock').textContent = pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }
  function stampUpdated() {
    var d = new Date();
    $('updated').textContent = '数据更新 ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }

  /* ---------------- 数字动画 ---------------- */
  // 统一补间：rAF 做动画，setTimeout 强制落地兜底（防止首屏渲染繁忙时 rAF 被延迟/丢弃）
  // 每次启动前取消该元素上一个动画，避免多个循环并发互相覆盖
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
    tween(el, function (e) {
      el.textContent = Math.round(target * e).toLocaleString('zh-CN');
    }, dur);
  }
  function ratioUp(el, target, dur) {
    if (target === null || target === undefined || isNaN(target)) { el.textContent = '–'; return; }
    target = Number(target);
    if (reduceMotion) { el.textContent = target.toFixed(1) + '%'; return; }
    tween(el, function (e) {
      el.textContent = (target * e).toFixed(1) + '%';
    }, dur);
  }

  /* ---------------- 关键读数 ---------------- */
  function sumTrend(t) {
    if (!t) return null;
    if (t.total_mentions !== null && t.total_mentions !== undefined) return t.total_mentions;
    return (t.daily_trend || []).reduce(function (a, d) {
      return a + (d.post_count || 0) + (d.comment_count || 0);
    }, 0);
  }
  function renderReadouts() {
    var t = state.trend, s = state.sentiment;
    var today = state.hot.today;
    var todayN = today ? (today.total !== undefined && today.total !== null ? today.total
      : (today.data ? today.data.length : 0)) : null;
    countUp($('post-count'), todayN, 900);
    if (t) countUp($('mention-count'), sumTrend(t), 1200);
    if (s) {
      ratioUp($('positive-ratio'), s.positive_ratio, 1000);
      countUp($('sample-size'), s.sample_size || s.total_analyzed, 900);
    }
  }

  /* ---------------- 情感仪表 + 负面频谱 ---------------- */
  function renderSentiment(s) {
    $('gauge-pos').style.width = (s.positive_ratio || 0) + '%';
    $('gauge-neu').style.width = (s.neutral_ratio || 0) + '%';
    $('gauge-neg').style.width = (s.negative_ratio || 0) + '%';
    $('sent-pos').textContent = s.positive_ratio == null ? '–' : Number(s.positive_ratio).toFixed(1) + '%';
    $('sent-neu').textContent = s.neutral_ratio == null ? '–' : Number(s.neutral_ratio).toFixed(1) + '%';
    $('sent-neg').textContent = s.negative_ratio == null ? '–' : Number(s.negative_ratio).toFixed(1) + '%';
    $('sent-sample-tag').textContent = '抽样 ' + num(s.sample_size || s.total_analyzed);
    renderNegSpectrum(s.top_negative_viewpoints || []);
  }
  function renderNegSpectrum(list) {
    var box = $('neg-spectrum');
    box.innerHTML = '';
    list = (list || []).slice(0, 10);
    if (!list.length) {
      box.innerHTML = '<p style="grid-column:1/-1;color:var(--ink-3);font-size:13px;">暂无负面观点词样本</p>';
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
      setTimeout(function () { row.querySelector('.spec-fill').style.width = w + '%'; }, 150 + i * 60);
    });
  }

  /* ---------------- 热点电讯 ---------------- */
  function validUrl(u) { return typeof u === 'string' && /^https:\/\/m\.weibo\.cn\/detail\/\d+$/.test(u); }
  function fmtTime(t) {
    if (!t) return '';
    if (/^\d{4}-\d{2}-\d{2}[T ]/.test(t)) {
      var d = new Date(t);
      if (!isNaN(d)) return pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) + ' ' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
    }
    return String(t).slice(5, 16).replace('T', ' ');
  }
  function emptyNode(kind) {
    var d = document.createElement('div');
    d.className = 'empty';
    var mark = '<svg class="empty-mark" viewBox="0 0 40 40" fill="none"><path d="M3 23h5l3-10 4 15 4-19 4 14h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var map = {
      pending: ['昨日数据补采进行中', '通常北京时间 08:30 后完成，稍后切换「昨日全日」查看'],
      error: ['暂时无法获取该时段数据', '可点击「刷新观测」重试，或稍后再试'],
      'today-empty': ['今日信号采集中', '第一条 AI 相关讨论出现后，将在此实时呈现'],
      other: ['当前时段暂无符合条件的 AI 行业讨论', '热点经 AI 相关性筛选，宁精勿滥']
    };
    var m = map[kind] || map.other;
    d.innerHTML = mark + '<p></p><small></small>';
    d.querySelector('p').textContent = m[0];
    d.querySelector('small').textContent = m[1];
    return d;
  }
  function wireItem(p, i, maxScore) {
    var a = document.createElement('a');
    a.className = 'wire-item';
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
    if (p.publish_time) {
      var tm = document.createElement('span');
      tm.className = 'wire-time';
      tm.textContent = fmtTime(p.publish_time);
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
    setTimeout(function () { a.classList.add('is-in'); }, 90 + i * 70);
    return a;
  }
  function renderPosts() {
    var mode = state.mode;
    var data = state.hot[mode];
    var status = state.status[mode];
    var box = $('posts');
    $('posts-label').textContent = mode === 'today' ? '今日 · 按热度排序' : '昨日全日 · 按热度排序';
    box.innerHTML = '';

    if (status === 'pending') { box.appendChild(emptyNode('pending')); $('posts-count-tag').textContent = '补采中'; return; }
    if (status === 'error' || !data) { box.appendChild(emptyNode('error')); $('posts-count-tag').textContent = '— 条'; return; }

    var list = data.data || [];
    $('posts-count-tag').textContent = list.length + ' 条';
    if (!list.length) { box.appendChild(emptyNode(mode === 'today' ? 'today-empty' : 'other')); return; }

    var maxScore = list.reduce(function (a, b) { return Math.max(a, b.hotspot_score || 0); }, 1);
    list.forEach(function (p, i) { box.appendChild(wireItem(p, i, maxScore)); });
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
    days: [], maxV: 1,
    hover: null, scan: 0, reveal: 0, t: 0, raf: null,
    pad: { l: 46, r: 14, t: 26, b: 30 },
    teal: '#34E8B0', amber: '#F2B45E',

    setup: function (trend) {
      var self = this;
      this.days = ((trend && trend.daily_trend) || []).map(function (d) {
        var post = d.post_count || 0, cmt = d.comment_count || 0;
        return { date: d.date, post: post, comment: cmt, total: post + cmt };
      });
      this.maxV = Math.max.apply(null, this.days.map(function (d) { return d.total; }).concat([1]));
      this.ctx = this.canvas.getContext('2d');
      this.reveal = reduceMotion ? 1 : 0;
      this.resize();
      this.updateReadout();
      if (!reduceMotion && !this.raf) this.animate();
    },
    resize: function () {
      var rect = this.canvas.getBoundingClientRect();
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
      $('wr-day').textContent = shortDate(d.date) + (isHover ? '' : ' · 峰值');
      $('wr-post').textContent = num(d.post);
      $('wr-comment').textContent = num(d.comment);
      $('wr-total').textContent = num(d.total);
    },
    bind: function () {
      var self = this;
      function idxFromEvent(e) {
        var rect = self.canvas.getBoundingClientRect();
        var cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
        var n = self.days.length;
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

      /* 水平刻度网格 + Y 值 */
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
        ctx.fillText(String(Math.round(maxV * k / 4)), 6, gy);
      }

      /* X 日期 */
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillStyle = 'rgba(95,117,107,.95)';
      for (var i2 = 0; i2 < n; i2++) {
        ctx.fillText(shortDate(this.days[i2].date), X(i2), y1 + 11);
      }

      var postPts = this.days.map(function (d, i) { return { x: X(i), y: Y(d.post) }; });
      var cmtPts = this.days.map(function (d, i) { return { x: X(i), y: Y(d.comment) }; });
      var clipX = x0 + this.reveal * (x1 - x0);

      /* 波形（随 reveal 从左绘出） */
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

      /* 峰值标注 */
      if (this.reveal >= 1) {
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

      /* hover 竖线 + 高亮点 */
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

      /* 横扫扫描线 */
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

  /* ---------------- 今日 / 昨日 切换 ---------------- */
  function switchMode(mode) {
    state.mode = mode;
    var t = $('tab-today'), y = $('tab-yesterday');
    t.classList.toggle('is-active', mode === 'today');
    t.setAttribute('aria-selected', mode === 'today');
    y.classList.toggle('is-active', mode === 'yesterday');
    y.setAttribute('aria-selected', mode === 'yesterday');
    if (state.status[mode] === null) ensureHot(mode);
    else renderPosts();
  }
  $('tab-today').addEventListener('click', function () { switchMode('today'); });
  $('tab-yesterday').addEventListener('click', function () { switchMode('yesterday'); });

  /* ---------------- 手动刷新 ---------------- */
  function reloadAll(animateBtn) {
    var btn = $('btn-refresh');
    if (animateBtn) btn.classList.add('is-loading');
    state.status.today = null;
    state.status.yesterday = null;
    return Promise.all([
      fetchJSON('trend-ai').then(function (d) { state.trend = d; wave.setup(d); }).catch(function () {}),
      fetchJSON('sentiment').then(function (d) { state.sentiment = d; renderSentiment(d); }).catch(function () {}),
      ensureHot('today'),
      ensureHot('yesterday')
    ]).then(function () {
      stampUpdated();
      renderReadouts();
      if (animateBtn) btn.classList.remove('is-loading');
    });
  }
  $('btn-refresh').addEventListener('click', function () { reloadAll(true); });

  /* 15 分钟静默自动刷新 */
  setInterval(function () { reloadAll(false); }, 15 * 60 * 1000);

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

  /* ---------------- 初始化（开机观测序列） ---------------- */
  tickClock();
  setInterval(tickClock, 1000);
  Promise.all([
    fetchJSON('trend-ai').then(function (d) { state.trend = d; wave.setup(d); }).catch(function () { wave.setup({ daily_trend: [] }); }),
    fetchJSON('sentiment').then(function (d) { state.sentiment = d; renderSentiment(d); }).catch(function () {}),
    ensureHot('today'),
    ensureHot('yesterday')
  ]).then(function () {
    stampUpdated();
    renderReadouts();
  });
  // 首屏渲染繁忙可能吞掉读数动画，页面稳定后强制重算一次兜底
  setTimeout(renderReadouts, 1500);
})();
