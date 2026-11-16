/* ============================================================
   OAS Studio · 前端
   数据流：REST(/api) + SSE(/api/runs/:id/stream)
   视图：总览（账号与模拟器） / 任务编排 / 执行记录 / 已知问题 / 高级
   ============================================================ */
(function () {
  'use strict';

  /* ---------------- 基础工具 ---------------- */
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  function el(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') node.className = v;
        else if (k === 'html') node.innerHTML = v;
        else if (k === 'text') node.textContent = v;
        else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
        else if (k.startsWith('data-')) node.setAttribute(k, v);
        else node.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const kid of kids.flat(9)) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return node;
  }

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const ICONS = {
    grid: '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="3.5" cy="6" r="1"/><circle cx="3.5" cy="12" r="1"/><circle cx="3.5" cy="18" r="1"/>',
    book: '<path d="M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2z"/><path d="M8 3v18"/>',
    play: '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l6 3.5-6 3.5z"/>',
    alert: '<path d="M12 3l9 16H3z"/><path d="M12 9v5"/><circle cx="12" cy="17" r=".6"/>',
    sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    trash: '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
    up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
    cog: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    refresh: '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    check: '<path d="M4 12.5l5 5L20 6.5"/>',
    users: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16.5 5.5a3 3 0 0 1 0 6M18 20a5.5 5.5 0 0 0-2-4.3"/>',
    power: '<path d="M12 3v9"/><path d="M7 6.5a8 8 0 1 0 10 0"/>',
    bolt: '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
    drag: '<circle cx="9" cy="7" r="1.2"/><circle cx="15" cy="7" r="1.2"/><circle cx="9" cy="12" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="9" cy="17" r="1.2"/><circle cx="15" cy="17" r="1.2"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
    phone: '<rect x="7" y="3" width="10" height="18" rx="2"/><path d="M11 18h2"/>',
  };
  const icon = (name, size) => `<svg viewBox="0 0 24 24" width="${size || 16}" height="${size || 16}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`;

  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    if (opts.body && typeof opts.body !== 'string') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, opts);
    let data = null;
    const text = await res.text();
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || res.statusText;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
  }

  function toast(message, kind) {
    const node = el('div', { class: 'toast ' + (kind || ''), text: message });
    $('#toasts').appendChild(node);
    setTimeout(() => { node.style.opacity = '0'; node.style.transition = 'opacity .2s'; }, 2600);
    setTimeout(() => node.remove(), 2900);
  }

  /* ---------------- 全局状态 ---------------- */
  const state = {
    view: 'overview',
    catalog: null,
    instances: [],
    devices: [],
    flows: [],
    flowLib: [],
    customPlans: [],
    jobs: [],
    runs: [],
    flowId: null,
    jobId: null,
    accountsDirty: false,
    flowsSignature: '',
  };

  const taskMeta = (key) => (state.catalog ? state.catalog.tasks.find((t) => t.key === key) : null) || { key, name: key, category: '其他', desc: '', team: false };
  const instName = (name) => {
    const inst = state.instances.find((i) => i.name === name);
    return inst ? inst.nickname || inst.name : name;
  };
  const instOf = (name) => state.instances.find((i) => i.name === name) || null;
  const currentFlow = () => state.flows.find((f) => f.id === state.flowId) || null;

  /* ---------------- 编排循环 ----------------
     loop 存在编排表上，启动时弹窗可临时覆盖并「记住为默认」。
     once=跑一遍 / count=重复 N 轮 / forever=一直循环直到手动停止。 */
  const normalizeLoop = (raw) => {
    const d = raw && typeof raw === 'object' ? raw : {};
    const mode = ['once', 'count', 'forever'].includes(d.mode) ? d.mode : 'once';
    let count = null;
    if (mode === 'once') count = 1;
    else if (mode === 'count') count = Math.max(2, Math.min(parseInt(d.count, 10) || 2, 999));
    const iv = (d.interval === undefined || d.interval === null || d.interval === '')
      ? 3 : parseInt(d.interval, 10);
    return {
      mode, count,
      on_error: d.on_error === 'continue' ? 'continue' : 'stop',
      interval: Number.isFinite(iv) ? Math.max(0, Math.min(iv, 300)) : 3,
    };
  };
  const loopLabel = (raw) => {
    const l = normalizeLoop(raw);
    return l.mode === 'forever' ? '一直循环'
      : l.mode === 'count' ? `循环 ${l.count} 轮` : '仅一次';
  };
  const loopRound = (job) => {
    if (!job || !job.round) return '';
    if (job.infinite) return `第 ${job.round} 轮 · 一直循环`;
    const total = job.total_rounds || 1;
    return total > 1 ? `第 ${job.round}/${total} 轮` : `第 ${job.round} 轮`;
  };

  /* 随机发呆：编排级配置，运行时注入自定义点击方案，不写进方案库。 */
  const normalizeIdle = (raw) => {
    const d = raw && typeof raw === 'object' ? raw : {};
    const sec = (v, def) => {
      const n = parseFloat(v);
      return Number.isFinite(n) ? Math.max(0, Math.min(n, 600)) : def;
    };
    let lo = sec(d.min, 2), hi = sec(d.max, 6);
    if (hi < lo) { const t = lo; lo = hi; hi = t; }
    const p = parseFloat(d.probability);
    return {
      enable: d.enable === true,
      min: Math.round(lo * 10) / 10,
      max: Math.round(hi * 10) / 10,
      probability: Number.isFinite(p) ? Math.max(0, Math.min(p, 1)) : 0.15,
    };
  };
  const idleLabel = (raw) => {
    const d = normalizeIdle(raw);
    return d.enable ? `随机发呆 ${Math.round(d.probability * 100)}% · ${d.min}~${d.max}s` : '随机发呆 关';
  };

  /* ---------------- 导航 ---------------- */
  const VIEWS = [
    { id: 'overview', label: '总览', icon: 'grid' },
    { id: 'flows', label: '任务编排', icon: 'list' },
    { id: 'runs', label: '执行记录', icon: 'play' },
    { id: 'issues', label: '已知问题', icon: 'alert' },
    { id: 'advanced', label: '高级设置', icon: 'sliders' },
  ];
  const VIEW_TITLE = Object.fromEntries(VIEWS.map((v) => [v.id, v.label]));

  function renderNav() {
    const nav = $('#nav');
    nav.innerHTML = '';
    VIEWS.forEach((v) => {
      const badge = v.id === 'overview' && state.instances.length
        ? el('span', { class: 'nav-badge', text: String(state.instances.length) }) : null;
      nav.appendChild(el('button', {
        class: 'nav-item' + (state.view === v.id ? ' active' : ''),
        'data-act': 'go', 'data-view': v.id, html: icon(v.icon) + `<span>${v.label}</span>`,
      }, badge));
    });
  }

  function go(view) {
    state.view = view;
    location.hash = '#' + view;
    renderNav();
    $('#crumbCur').textContent = VIEW_TITLE[view] || view;
    render();
  }

  function render() {
    const view = $('#view');
    const scroll = view.scrollTop;
    view.innerHTML = '';
    $('#crumbCur').textContent = VIEW_TITLE[state.view] || state.view;
    const map = {
      overview: renderOverview, flows: renderFlows,
      runs: renderRuns, issues: renderIssues, advanced: renderAdvanced,
    };
    (map[state.view] || renderOverview)(view);
    view.scrollTop = state.view === 'flows' ? scroll : 0;
    $('#topActions').innerHTML = '';
    renderTopActions();
  }

  function renderTopActions() {
    const box = $('#topActions');
    if (state.view === 'overview') {
      box.append(
        btn('刷新设备', 'refresh', () => loadDevices(true), 'ghost'),
        btn('绑定新账号', 'plus', openBindDrawer, 'primary'),
      );
    } else if (state.view === 'flows') {
      // 执行是「每份编排一个按钮」（在左侧列表里），顶栏只留新建。
      box.append(btn('新建编排', 'plus', () => openNewFlowDrawer(), 'ghost'));
    } else if (state.view === 'runs') {
      box.append(btn('刷新', 'refresh', () => loadRuns(true), 'ghost'));
    }
  }

  function btn(label, ico, onClick, kind, size) {
    const b = el('button', { class: 'btn' + (kind ? ' btn-' + kind : '') + (size ? ' btn-' + size : ''), html: icon(ico) + `<span>${esc(label)}</span>` });
    b.addEventListener('click', onClick);
    return b;
  }

  /* ---------------- 数据加载 ---------------- */
  async function loadCatalog(force) {
    if (state.catalog && !force) return;
    state.catalog = await api('/api/catalog');
    renderNav();
  }

  async function loadInstances() {
    const data = await api('/api/instances');
    state.instances = data.instances || [];
  }

  async function loadDevices(notify) {
    try {
      // 用户点「刷新设备」时带上 probe，让 bridge 主动 connect 一遍已知端口
      // （新开的模拟器实例不会自己注册到 adb server）。
      const data = await api('/api/devices' + (notify ? '?probe=1' : ''));
      state.devices = data.devices || [];
      if (notify) toast(`扫描完成，在线设备 ${state.devices.length} 台`, state.devices.length ? 'ok' : 'err');
    } catch (e) { if (notify) toast('扫描失败：' + e.message, 'err'); }
    if (state.view === 'overview') render();
  }

  async function loadFlows() {
    const data = await api('/api/flows');
    state.flows = data.flows || [];
    if (!state.flowId && state.flows.length) state.flowId = state.flows[0].id;
    if (state.flowId && !state.flows.some((f) => f.id === state.flowId)) {
      state.flowId = state.flows.length ? state.flows[0].id : null;
    }
  }

  async function loadFlowLib() {
    try { state.flowLib = (await api('/api/flow-library')).templates || []; }
    catch (e) { state.flowLib = []; }
  }

  async function loadJobs() {
    const data = await api('/api/jobs');
    state.jobs = data.jobs || [];
  }

  async function loadRuns() {
    const data = await api('/api/runs');
    state.runs = data.runs || [];
  }

  async function loadVersion() {
    try {
      const v = await api('/api/version');
      const node = $('#appVersion');
      if (node) node.textContent = `v${v.version || '?'} · ${v.build || 'release'}`;
    } catch (e) {
      const node = $('#appVersion');
      if (node) node.textContent = '版本未知（桥接未连接）';
    }
  }

  async function refreshAll() {
    await Promise.all([loadVersion(), loadCatalog(), loadInstances(), loadFlows(),
      loadFlowLib(), loadCustomPlans(), loadJobs(), loadRuns()]);
    await loadDevices();
    render();
  }

  /* ---------------- 总览（账号与模拟器） ---------------- */
  function renderOverview(root) {
    // 一个账号 = 一台模拟器。卡片只回答两件事：这台模拟器是谁、正在做什么。
    if (!state.instances.length) {
      root.appendChild(el('div', { class: 'empty' },
        el('div', { html: icon('link', 26) }),
        el('strong', { text: '还没有绑定账号' }),
        el('p', { text: '选择一台在线模拟器，填写游戏昵称与区服。双开就绑两个，可编进同一张编排表做联动。' }),
        btn('绑定账号', 'plus', openBindDrawer, 'primary'),
      ));
    } else {
      const grid = el('div', { class: 'grid grid-2' });
      state.instances.forEach((inst) => grid.appendChild(accountCard(inst)));
      root.appendChild(grid);
    }
    root.appendChild(el('p', {
      class: 'small muted mt-8',
      text: '模拟器分辨率需设置为 1280×720，否则任务无法正常运行。',
    }));

    // 检测到但还没绑定的模拟器，给一条窄表就够
    const unbound = state.devices.filter((d) => !d.bound_to);
    if (unbound.length) {
      root.appendChild(el('div', { class: 'section-title mt-20' },
        el('h2', { text: '未绑定的模拟器' }),
        el('span', { class: 'sub', text: 'MuMu 12 多开端口从 16384 起递增。' }),
      ));
      const table = el('table', { class: 'table' });
      table.innerHTML = '<thead><tr><th>设备</th><th>型号</th><th>分辨率</th><th></th></tr></thead>';
      const tbody = el('tbody');
      unbound.forEach((d) => {
        tbody.appendChild(el('tr', {},
          el('td', { class: 'mono', text: d.serial }),
          el('td', { class: 'muted', text: d.model || '—' }),
          el('td', { class: 'mono', text: d.resolution || '—' }),
          el('td', {}, el('button', { class: 'btn btn-sm', text: '绑定为账号', 'data-act': 'bindDevice', 'data-serial': d.serial })),
        ));
      });
      table.appendChild(tbody);
      root.appendChild(el('div', { class: 'panel' }, el('div', { class: 'panel-body', style: 'padding:0' }, table)));
    } else if (!state.devices.length) {
      root.appendChild(el('p', {
        class: 'small muted mt-20',
        text: 'adb 没有扫描到在线设备。点「绑定新账号」可手动填写 adb 地址（本机 MuMu 常用 127.0.0.1:16384，多开依次 +32）直接连接；模拟器刚启动时也可以先点「刷新设备」。',
      }));
    }
  }

  function statCard(k, v, m, tone) {
    return el('div', { class: 'stat' },
      el('div', { class: 'k', text: k }),
      el('div', { class: 'v' + (tone === 'ok' ? '' : '') }, v),
      el('div', { class: 'm', text: m }),
    );
  }

  function statusBadge(status) {
    const map = {
      running: ['badge-accent', '运行中'], finished: ['badge-ok', '已完成'],
      failed: ['badge-err', '失败'], cancelled: ['badge-warn', '已取消'],
      ok: ['badge-ok', '成功'], fail: ['badge-err', '失败'], skipped: ['badge-dim', '跳过'],
      pending: ['badge-dim', '待执行'],
    };
    const [cls, label] = map[status] || ['badge-dim', status || '—'];
    return el('span', { class: 'badge ' + cls, text: label });
  }

  function accountCard(inst) {
    // 紧凑两行：第一行是谁（昵称/区服）+ 两个动作，第二行在哪（模拟器 ID/分辨率/在跑什么）。
    // 「编排表」归编排页管，卡片上不再重复；「测试连接」由刷新设备覆盖，也不再占位。
    const device = state.devices.find((d) => d.serial === inst.serial) || null;
    const act = instActivity(inst);
    const serial = inst.serial || '未绑定模拟器';
    const card = el('div', { class: 'acct' });
    const initial = (inst.nickname || inst.name).slice(0, 1).toUpperCase();

    card.appendChild(el('div', { class: 'acct-row' },
      el('div', { class: 'avatar' + (inst.primary ? '' : ' sub'), text: initial }),
      el('strong', { class: 'acct-name', title: inst.nickname || inst.name, text: inst.nickname || inst.name }),
      el('span', { class: 'acct-server', text: inst.server ? `${inst.server} · ${inst.role_id || '未填ID'}` : '未填区服' }),
      el('div', { class: 'grow' }),
      el('div', { class: 'acct-actions' },
        btn('编辑资料', 'sliders', () => openProfileDrawer(inst), 'ghost', 'sm'),
        btn('解绑', 'trash', () => removeInstance(inst.name), 'danger', 'sm'),
      ),
    ));

    card.appendChild(el('div', { class: 'acct-row acct-row-meta' },
      el('span', { class: 'dot ' + (inst.online ? 'dot-ok' : 'dot-err') }),
      el('span', { class: 'acct-serial', title: serial, text: serial }),
      device && device.resolution ? el('span', { class: 'muted', text: '· ' + device.resolution }) : null,
      !device ? el('span', { class: 'muted', text: '· 未扫描到' }) : null,
      !inst.online ? el('span', { class: 'muted', text: '· 离线' }) : null,
      act.tone === 'run' ? el('span', { class: 'badge badge-accent', text: '执行中' }) : null,
      act.tone === 'run' && act.detail
        ? el('span', { class: 'acct-act-text muted', title: act.detail, text: act.detail }) : null,
    ));
    return card;
  }

  function instActivity(inst) {
    // 只保留「是否在跑、跑什么」：在线状态由第二行的圆点表示，不再重复一行徽章
    if (!inst.online) return { tone: 'off', detail: '' };
    const run = state.runs.find((r) => r.instance === inst.name && r.status === 'running');
    if (!run) return { tone: 'idle', detail: '' };
    const flow = state.jobs.find((j) => j.id === run.batch);
    return {
      tone: 'run',
      detail: taskMeta(run.task).name + (flow ? ` · ${flow.flow_name}` : ''),
    };
  }

  /* ---------------- 账号绑定操作 ---------------- */

  async function removeInstance(name) {
    const last = state.instances.length <= 1;
    const tip = last
      ? `确定解绑账号 ${name}？\n这是最后一个账号，解绑后总览会变成空态，随时可以重新绑定。`
      : `确定解绑账号 ${name}？\n配置将被删除且不保留备份，编排表里的引用会一并摘掉。`;
    if (!confirm(tip)) return;
    try {
      const r = await api(`/api/instances/${name}`, { method: 'DELETE' });
      if (r && r.remaining === 0) toast('已解绑，当前没有账号了，可重新绑定', 'ok');
      else toast('已解绑', 'ok');
      await loadInstances();
      render();
    } catch (e) { toast('解绑失败：' + e.message, 'err'); }
  }

  function openBindDrawer(serial) {
    const devices = state.devices.filter((d) => !d.bound_to);
    const body = el('div');
    const nameInput = el('input', { class: 'input', placeholder: '英文/数字，如 oas2（与配置文件同名）', value: suggestName() });
    const nickInput = el('input', { class: 'input', placeholder: '游戏内昵称，如 晴明' });
    const serverInput = el('input', { class: 'input', placeholder: '区服，如 形影不离 / S12' });
    const roleInput = el('input', { class: 'input', placeholder: '角色 ID（可留空）' });
    const primary = el('input', { type: 'checkbox' });

    // adb 地址必须可手填：跨机、以及新开的模拟器实例，adb 都不会自动出现在扫描结果里。
    const listId = 'adb-serial-list';
    const serialInput = el('input', {
      class: 'input',
      list: listId,
      placeholder: '127.0.0.1:16384（本机）或 192.168.1.50:16384（局域网）',
      value: serial || (devices.length ? devices[0].serial : ''),
    });
    const datalist = el('datalist', { id: listId });
    const fillList = (list) => {
      datalist.innerHTML = '';
      list.forEach((d) => datalist.appendChild(el('option', {
        value: d.serial,
        text: `${d.serial}${d.model ? ' · ' + d.model : ''}${d.resolution ? ' · ' + d.resolution : ''}`,
      })));
    };
    fillList(state.devices);

    const connectBtn = btn('连接', 'bolt', async () => {
      const value = serialInput.value.trim();
      if (!value) return toast('请先填写 adb 地址', 'err');
      connectBtn.disabled = true;
      try {
        const data = await api('/api/devices/connect', { method: 'POST', body: { serial: value } });
        state.devices = data.devices || state.devices;
        fillList(state.devices);
        if (data.ok) toast(`已连接 ${value}`, 'ok');
        else toast('连接失败：' + (data.output || '地址不可达'), 'err');
        if (state.view === 'overview') render();
      } catch (e) {
        toast('连接失败：' + e.message, 'err');
      } finally { connectBtn.disabled = false; }
    }, 'ghost');

    body.append(
      field('实例名（配置文件名）', nameInput, '英文短名，用于 config/<name>.json，也是编排表里的账号标识。'),
      field('adb 地址', el('div', { class: 'row' }, serialInput, connectBtn),
        devices.length
          ? '从下拉里选一台已扫描到的模拟器，或直接填写端口/局域网地址后点「连接」。'
          : '没有扫描到模拟器？填写 adb 地址（MuMu 12 单开是 127.0.0.1:16384，多开依次 +32）后点「连接」。'),
      el('div', { class: 'form-grid' },
        field('游戏昵称', nickInput),
        field('区服', serverInput),
      ),
      el('div', { class: 'form-grid' },
        field('角色 ID', roleInput, '仅用于界面区分，可留空。'),
        el('div', { class: 'field' }, el('label', { text: '主号' }),
          el('label', { class: 'switch' }, primary, el('span', { class: 'track' }),
            el('span', { class: 'small muted', text: '作为默认队长端' }))),
      ),
    );

    openDrawer({
      kicker: '账号绑定',
      title: '绑定新账号',
      body,
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('创建并绑定', 'check', async () => {
          const name = nameInput.value.trim();
          const serial = serialInput.value.trim();
          if (!/^[A-Za-z0-9_-]{2,32}$/.test(name)) return toast('实例名需为 2-32 位字母/数字/下划线', 'err');
          if (!serial) return toast('请选择或填写 adb 地址', 'err');
          try {
            // 手填的地址可能还没连上，先 connect 一次再把实例写进去，
            // 否则后续任务会因为 serial 不可达直接失败。
            if (!state.devices.some((d) => d.serial === serial)) {
              const conn = await api('/api/devices/connect', { method: 'POST', body: { serial } });
              if (!conn.ok) return toast('adb 连接失败：' + (conn.output || '地址不可达'), 'err');
              state.devices = conn.devices || state.devices;
            }
            await api('/api/instances', { method: 'POST', body: { name, serial } });
            await api(`/api/profiles/${name}`, {
              method: 'PUT',
              body: { nickname: nickInput.value.trim() || name, server: serverInput.value.trim(), role_id: roleInput.value.trim(), primary: primary.checked },
            });
            toast('账号已绑定', 'ok');
            closeDrawer();
            await loadInstances();
            await loadDevices();
            render();
          } catch (e) { toast('绑定失败：' + e.message, 'err'); }
        }, 'primary'),
      ],
    });
  }

  function suggestName() {
    let i = 1;
    while (state.instances.some((x) => x.name === 'oas' + i)) i += 1;
    return 'oas' + i;
  }

  function openProfileDrawer(inst) {
    const nickInput = el('input', { class: 'input', value: inst.nickname || '' });
    const serverInput = el('input', { class: 'input', value: inst.server || '' });
    const roleInput = el('input', { class: 'input', value: inst.role_id || '' });
    const primary = el('input', { type: 'checkbox', checked: inst.primary });
    const body = el('div', {},
      field('游戏昵称', nickInput),
      el('div', { class: 'form-grid' }, field('区服', serverInput), field('角色 ID', roleInput)),
      el('div', { class: 'field' }, el('label', { text: '主号（默认队长端）' }),
        el('label', { class: 'switch' }, primary, el('span', { class: 'track' }))),
      el('p', { class: 'hint', text: '这些信息只保存在 config/gui_profiles.json，不会写入引擎配置，也不影响执行。' }),
    );
    openDrawer({
      kicker: '账号绑定',
      title: '编辑账号资料 · ' + inst.name,
      body,
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => {
          try {
            await api(`/api/profiles/${inst.name}`, {
              method: 'PUT',
              body: { nickname: nickInput.value.trim(), server: serverInput.value.trim(), role_id: roleInput.value.trim(), primary: primary.checked },
            });
            toast('已保存', 'ok');
            closeDrawer();
            await loadInstances();
            render();
          } catch (e) { toast('保存失败：' + e.message, 'err'); }
        }, 'primary'),
      ],
    });
  }

  /* ---------------- 任务编排 ---------------- */
  /* ---------------- 任务编排：账号 → 多份编排 + 选中编排的步骤 ----------------
     一个账号可以有多份编排，左栏逐份列出、点哪份看哪份；每份编排自带一个
     执行按钮。同一账号同一时间只能跑一份，所以有编排在跑时，同账号下其它
     编排的执行按钮直接锁住（后端 run_flow 也会挡，见 gui/bridge.py）。     */
  // 编排归组跟随「实际队长」：有自定义组队时以显式队长为准，否则才是第一个账号。
  const flowOwner = (flow) => {
    const ts = (flow.steps || []).find((s) => s.task === 'team_setup' && s.team && s.team.leader);
    return (ts && ts.team.leader && (flow.accounts || []).includes(ts.team.leader))
      ? ts.team.leader : ((flow.accounts && flow.accounts[0]) || '');
  };
  const runningJobOf = (flowId) => state.jobs.find(
    (j) => j.flow_id === flowId && j.status === 'running') || null;

  function accountBusy(name) {
    return state.jobs.some((job) => {
      if (job.status !== 'running') return false;
      const flow = state.flows.find((f) => f.id === job.flow_id);
      return !!(flow && flow.accounts.includes(name));
    });
  }

  const flowLocked = (flow) => flow.accounts.some(accountBusy);

  function selectFlow(id) {
    if (state.flowId === id) return;
    state.flowId = id;
    render();
  }

  function renderFlows(root) {
    if (!state.instances.length) {
      root.appendChild(el('div', { class: 'empty' },
        el('div', { html: icon('link', 26) }),
        el('strong', { text: '还没有绑定账号' }),
        el('p', { text: '编排表挂在账号下面：先绑定一台模拟器，再给它编一份要跑的任务顺序。一个账号可以有多份，切换着用。' }),
        btn('绑定账号', 'plus', openBindDrawer, 'primary'),
      ));
      return;
    }

    if (!state.flowId && state.flows.length) state.flowId = state.flows[0].id;

    // 按「首个账号」分组：多账号联动的编排归到队长名下，避免同一份出现两次。
    const known = new Set(state.instances.map((i) => i.name));
    const groups = new Map(state.instances.map((inst) => [inst.name, []]));
    state.flows.forEach((flow) => {
      // 账号每次启动都要重新绑定；引用了「当前不存在账号」的编排归入任务库，
      // 不能让它凭空消失，任务是通用模板。
      const owner = flowOwner(flow);
      const key = known.has(owner) ? owner : '';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(flow);
    });

    const layout = el('div', { class: 'fl-layout' });
    const side = el('aside', { class: 'fl-side' });
    const detail = el('section', { class: 'fl-detail' });
    layout.append(side, detail);
    root.appendChild(layout);

    state.instances.forEach((inst) => side.appendChild(flowGroup(inst, groups.get(inst.name) || [])));

    // 数据异常（账号被解绑）的编排不能凭空消失，单独挂一组，让用户能删掉或改绑。
    const orphans = groups.get('') || [];
    if (orphans.length) {
      const group = el('div', { class: 'fl-group' });
      group.appendChild(el('div', { class: 'fl-group-head' },
        el('strong', { class: 'grow', text: '任务库（未绑定账号）' })));
      group.appendChild(el('div', { class: 'fl-none',
        text: '这些是通用任务模板：先绑定账号，再用编排的「改绑定」挂到任意账号。' }));
      orphans.forEach((flow) => group.appendChild(flowItem(flow)));
      side.appendChild(group);
    }

    side.appendChild(el('button', { class: 'fl-new', 'data-act': 'newFlow' },
      el('span', { html: icon('plus', 13) }), el('span', { text: '新建编排' })));

    renderFlowDetail(detail);
    // 记住这一帧的「谁在跑」，轮询发现变化才重绘，避免每 5 秒把步骤进度刷掉。
    state.flowsSignature = runningSignature();
  }

  // 带上轮次：循环作业每进入新一轮时重绘一次，标题上的「第 N 轮」才会跟着走
  const runningSignature = () => state.jobs
    .filter((j) => j.status === 'running')
    .map((j) => `${j.id}:${j.round || 0}`).sort().join(',');

  function flowGroup(inst, flows) {
    const group = el('div', { class: 'fl-group' });
    group.appendChild(el('div', { class: 'fl-group-head' },
      el('div', { class: 'avatar' + (inst.primary ? '' : ' sub'),
        text: (inst.nickname || inst.name).slice(0, 1).toUpperCase() }),
      el('div', { class: 'fl-group-id' },
        el('strong', { text: inst.nickname || inst.name }),
        el('span', { text: inst.serial || '未绑定模拟器' }),
      ),
      el('div', { class: 'grow' }),
      el('button', {
        class: 'icon-btn', title: '给这个账号新建编排',
        'data-act': 'newFlow', 'data-account': inst.name, html: icon('plus', 13),
      }),
    ));
    if (!flows.length) group.appendChild(el('div', { class: 'fl-none', text: '还没有编排' }));
    flows.forEach((flow) => group.appendChild(flowItem(flow)));
    return group;
  }

  function flowItem(flow) {
    const job = runningJobOf(flow.id);
    const running = !!job;
    const locked = !running && flowLocked(flow);
    const meta = [`${flow.steps.length} 步`];
    if (flow.accounts.length > 1) meta.push(`${flow.accounts.length} 账号联动`);
    const lp = loopLabel(flow.loop);
    if (lp !== '仅一次') meta.push(lp);
    const idl = normalizeIdle(flow.idle);
    if (idl.enable) meta.push(`发呆 ${Math.round(idl.probability * 100)}%`);
    if (running) meta.push(loopRound(job) || '执行中');

    const item = el('div', {
      class: 'fl-item' + (state.flowId === flow.id ? ' active' : '') + (running ? ' running' : ''),
      'data-act': 'selectFlow', 'data-id': flow.id,
    }, el('div', { class: 'fl-item-main' },
      el('div', { class: 'fl-name', text: flow.name }),
      el('div', { class: 'fl-meta', text: meta.join(' · ') }),
    ));

    const act = el('button', {
      class: 'fl-run' + (running ? ' stop' : ''),
      title: running ? '停止执行' : (locked ? '该账号正在执行其它编排'
        : `按「${loopLabel(flow.loop)}」执行（在「循环设置」里改）`),
      'data-act': running ? 'stopJob' : 'runFlow',
      'data-id': running ? job.id : flow.id,
      html: icon(running ? 'x' : 'play', 12) + `<span>${running ? '停止' : '执行'}</span>`,
    });
    if (locked) act.disabled = true;
    item.appendChild(act);
    return item;
  }

  function renderFlowDetail(detail) {
    const flow = currentFlow();
    if (!flow) {
      detail.appendChild(el('div', { class: 'empty' },
        el('div', { html: icon('list', 26) }),
        el('strong', { text: '还没有选中编排' }),
        el('p', { text: '左侧每个账号下可以有多份编排：点一份就能编辑它的任务顺序，点圆按钮直接执行。' }),
        btn('新建编排', 'plus', () => openNewFlowDrawer(), 'primary'),
      ));
      return;
    }

    const job = runningJobOf(flow.id);
    const head = el('div', { class: 'fl-detail-head' });
    head.appendChild(el('div', { class: 'fl-title' },
      el('h2', { text: flow.name }),
      job ? el('span', { class: 'badge badge-accent', text: '执行中' }) : null,
      el('span', { class: 'badge ' + (flow.accounts.length > 1 ? 'badge-gold' : 'badge-dim'),
        text: flow.accounts.length > 1 ? `${flow.accounts.length} 账号联动` : '单账号' }),
      el('span', { class: 'badge badge-dim', text: `${flow.steps.length} 步` }),
      el('span', { class: 'badge ' + (normalizeLoop(flow.loop).mode === 'once' ? 'badge-dim' : 'badge-gold'),
        text: loopLabel(flow.loop) }),
      el('span', { class: 'badge ' + (normalizeIdle(flow.idle).enable ? 'badge-gold' : 'badge-dim'),
        text: idleLabel(flow.idle) }),
    ));
    head.appendChild(el('div', { class: 'row' },
      btn(job ? '停止执行' : '执行', job ? 'x' : 'play',
        job ? () => stopJob(job.id) : () => runFlow(flow), job ? 'danger' : 'primary'),
      btn('随机发呆', 'moon', () => openIdleDrawer(flow), 'ghost'),
      btn('循环设置', 'refresh', () => openLoopDrawer(flow), 'ghost'),
      btn('改绑定', 'cog', () => openFlowBindDrawer(flow), 'ghost'),
      btn('重命名', 'sliders', () => renameFlow(flow), 'ghost'),
      btn('存为自定义方案', 'copy', () => saveFlowAsTemplate(flow), 'ghost'),
      btn('删除', 'trash', () => deleteFlow(flow), 'ghost'),
    ));
    head.appendChild(el('div', { class: 'fl-bind' },
      el('span', { class: 'small muted', text: '绑定账号' }),
      flow.accounts.map((acct) => el('span', { class: 'badge badge-accent', text: instName(acct) })),
    ));
    detail.appendChild(head);

    // 只有正在跑的时候才显示执行条；跑完就收起，不保留「最近一次执行」。
    if (job) {
      const done = job.steps.filter((s) => ['ok', 'fail', 'skipped'].includes(s.status)).length;
      const bar = el('div', { class: 'panel', style: 'margin-bottom:14px' });
      bar.appendChild(el('div', { class: 'panel-head' },
        el('h3', {}, '正在执行 ', statusBadge(job.status)),
        el('div', { class: 'row' },
          el('span', { class: 'sub', text: `${loopRound(job) ? loopRound(job) + ' · ' : ''}${done}/${job.steps.length} 步 · ${(job.started || '').replace('T', ' ')}` }),
          btn('停止', 'x', () => stopJob(job.id), 'danger'),
        ),
      ));
      detail.appendChild(bar);
    }

    const steps = el('div', { class: 'steps' });
    if (!flow.steps.length) {
      detail.appendChild(el('div', { class: 'empty' },
        el('div', { html: icon('book', 26) }),
        el('strong', { text: '这份编排还是空的' }),
        el('p', { text: '点下面「添加任务」，按玩法分类挑选，配置好参数就能加入列表，再用箭头调整顺序。' }),
      ));
    }
    flow.steps.forEach((step, idx) => steps.appendChild(stepRow(flow, step, idx, job)));
    detail.appendChild(steps);

    const addBar = el('div', { style: 'margin-top:12px; display:flex; gap:8px;' });
    addBar.append(
      btn('添加任务', 'plus', () => openTaskPicker(), 'primary'),
      btn('自定义组队', 'users', () => openTeamDrawer(null), flow.accounts.length > 1 ? '' : 'ghost'),
      btn('从方案创建', 'copy', () => openTemplatePicker(), 'ghost'),
    );
    detail.appendChild(addBar);

    // 联动说明
    if (flow.accounts.length > 1) {
      detail.appendChild(el('div', { class: 'panel', style: 'margin-top:18px' },
        el('div', { class: 'panel-head' }, el('h3', { text: '组队联动说明' })),
        el('div', { class: 'panel-body' },
          el('p', { class: 'small muted', text: '联动分两步：先插入一条「自定义组队」指定队长与队员（队长不必是第一个账号，编排会归到队长名下），再把带「可联动」标记的玩法设为「组队执行」。' }),
          el('p', { class: 'small muted mt-8', text: '执行时队长写入 user_status=leader、队员写入 member；同时把队员的「游戏内昵称」自动回填到队长 invite_config.friend_1/2，队长按昵称在好友列表里 OCR 精确匹配后发出邀请。' }),
          el('p', { class: 'small muted mt-8', text: '前提：两账号互为好友或同寮、队员在线且启动前停在庭院，绑定资料里的「游戏内昵称」必须填游戏内全称。引擎最多邀请 2 名队员，3 人及以上暂不支持。' }),
        ),
      ));
    }
  }

  function stepRow(flow, step, idx, job) {
    if (step.task === 'team_setup') return teamStepRow(flow, step, idx, job);
    const meta = taskMeta(step.task);
    const running = job && job.status === 'running' && job.index === idx;
    const stepState = job && job.steps[idx] ? job.steps[idx].status : null;
    const summary = stepSummary(flow, step);

    const row = el('div', { class: 'step', 'data-step': step.id });
    row.appendChild(el('div', { class: 'step-num' },
      el('span', { text: String(idx + 1).padStart(2, '0') }),
      el('span', { class: 'step-drag', html: icon('drag', 14) }),
    ));

    const line1 = el('div', { class: 'step-line1' },
      el('span', { class: 'name', text: meta.name }),
      el('span', { class: 'badge badge-dim', text: meta.category }),
      step.mode === 'team' ? el('span', { class: 'badge badge-gold', text: '组队联动' }) : null,
      (step.mode !== 'team' && step.account && (flow.accounts || []).length > 1)
        ? el('span', { class: 'badge badge-accent', text: instName(step.account) }) : null,
      stepState ? (() => { const b = statusBadge(stepState); b.setAttribute('data-status', '1'); return b; })() : null,
    );

    const line2 = el('div', { class: 'step-line2' });
    if (summary.length) {
      summary.forEach((s) => line2.appendChild(el('span', { class: 'kv', text: s })));
    } else {
      line2.appendChild(el('span', { text: '使用账号当前配置' }));
    }

    const main = el('div', { class: 'step-main' }, line1, line2);
    if (step.mode === 'team') {
      const team = el('div', { class: 'duo-split' });
      const members = effectiveRoster(flow, idx);
      members.forEach((acct, i) => {
        team.appendChild(el('div', { class: 'duo-lane' },
          el('span', { class: 'badge ' + (i === 0 ? 'badge-gold' : 'badge-dim'), text: i === 0 ? '队长' : '队员' }),
          el('b', { text: instName(acct) }),
        ));
      });
      main.appendChild(team);
    }
    row.appendChild(main);

    row.appendChild(el('div', { class: 'step-ops' },
      el('button', { class: 'icon-btn', title: '上移', 'data-act': 'stepUp', 'data-id': step.id, html: icon('up', 13) }),
      el('button', { class: 'icon-btn', title: '下移', 'data-act': 'stepDown', 'data-id': step.id, html: icon('down', 13) }),
      step.task === 'custom_click'
        ? el('button', { class: 'icon-btn', title: '更换方案', 'data-act': 'customClickSwap', 'data-id': step.id, html: icon('copy', 13) })
        : null,
      el('button', { class: 'icon-btn', title: step.task === 'custom_click' ? '编辑自定义点击方案' : '配置参数',
        'data-act': step.task === 'custom_click' ? 'customClickConfig' : 'stepConfig',
        'data-id': step.id, html: icon('cog', 13) }),
      el('button', { class: 'icon-btn', title: '删除', 'data-act': 'stepDelete', 'data-id': step.id, html: icon('trash', 13) }),
    ));
    return row;
  }

  // 组队步骤沿用它之前最近的一条「自定义组队」；没有则退回编排表账号顺序
  function effectiveRoster(flow, idx) {
    const ts = flow.steps.slice(0, idx)
      .filter((s) => s.task === 'team_setup' && s.team && s.team.leader).pop();
    if (ts) return [ts.team.leader].concat(ts.team.members || []);
    return flow.accounts;
  }

  function teamStepRow(flow, step, idx, job) {
    const row = el('div', { class: 'step team-step' });
    row.appendChild(el('div', { class: 'step-num' },
      el('span', { text: String(idx + 1).padStart(2, '0') }),
      el('span', { class: 'step-drag', html: icon('drag', 14) }),
    ));
    const team = step.team || {};
    const leader = team.leader ? instName(team.leader) : '未指定';
    const members = (team.members || []).map(instName);
    const main = el('div', { class: 'step-main' },
      el('div', { class: 'step-line1' },
        el('span', { class: 'name', text: '自定义组队' }),
        el('span', { class: 'badge badge-gold', text: '队伍配置' }),
        !team.leader ? el('span', { class: 'badge badge-warn', text: '缺少队长' }) : null,
      ),
      el('div', { class: 'step-line2' },
        el('span', { class: 'kv', text: '队长 ' + leader }),
        el('span', { class: 'kv', text: '队员 ' + (members.length ? members.join('、') : '无') }),
        el('span', { text: '后续组队玩法沿用此队伍' }),
      ),
    );
    row.appendChild(main);
    row.appendChild(el('div', { class: 'step-ops' },
      el('button', { class: 'icon-btn', title: '上移', 'data-act': 'stepUp', 'data-id': step.id, html: icon('up', 13) }),
      el('button', { class: 'icon-btn', title: '下移', 'data-act': 'stepDown', 'data-id': step.id, html: icon('down', 13) }),
      el('button', { class: 'icon-btn', title: '编辑队伍', 'data-act': 'teamConfig', 'data-id': step.id, html: icon('users', 13) }),
      el('button', { class: 'icon-btn', title: '删除', 'data-act': 'stepDelete', 'data-id': step.id, html: icon('trash', 13) }),
    ));
    return row;
  }

  function openTeamDrawer(stepId) {
    const flow = currentFlow();
    if (!flow) return;
    if (flow.accounts.length < 2) {
      toast('至少绑定 2 个账号才能组队', 'warn');
      return;
    }
    const step = stepId ? flow.steps.find((s) => s.id === stepId) : null;
    const saved = (step && step.team) || {};
    let leader = saved.leader || flow.accounts[0];
    let members = (saved.members || flow.accounts.filter((a) => a !== leader)).slice();

    const body = el('div');
    const leaderBox = el('div', { class: 'chips' });
    const memberBox = el('div', { class: 'chips' });
    function paint() {
      leaderBox.innerHTML = '';
      memberBox.innerHTML = '';
      flow.accounts.forEach((acct) => {
        const chip = el('button', { class: 'chip' + (leader === acct ? ' active' : ''), text: instName(acct) });
        chip.addEventListener('click', () => {
          leader = acct;
          members = members.filter((m) => m !== acct);
          paint();
        });
        leaderBox.appendChild(chip);
      });
      flow.accounts.filter((a) => a !== leader).forEach((acct) => {
        const on = members.includes(acct);
        const chip = el('button', { class: 'chip' + (on ? ' active' : ''), text: instName(acct) });
        chip.addEventListener('click', () => {
          members = on ? members.filter((m) => m !== acct) : members.concat(acct);
          paint();
        });
        memberBox.appendChild(chip);
      });
      hint.textContent = members.length
        ? `队长：${instName(leader)} · 队员：${members.map(instName).join('、')}（共 ${members.length + 1} 人）`
        : '请至少选择 1 名队员。';
    }
    const hint = el('p', { class: 'hint' });
    body.append(
      el('p', { class: 'hint', style: 'margin-bottom:14px', text: '这条步骤不执行游戏操作，只把多个账号编成一队。后面的组队玩法（御魂/觉醒/探索等）会自动沿用这里的队长与队员。' }),
      el('div', { class: 'field' }, el('label', { text: '队长（负责建房、邀请）' }), leaderBox),
      el('div', { class: 'field' }, el('label', { text: '队员（负责接受邀请）' }), memberBox),
      hint,
    );
    paint();

    openDrawer({
      kicker: '组队',
      title: stepId ? '编辑队伍' : '添加自定义组队',
      body,
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn(stepId ? '保存' : '加入编排', 'check', async () => {
          if (!members.length) return toast('请至少选择 1 名队员', 'err');
          const team = { leader, members };
          if (stepId) {
            const target = flow.steps.find((s) => s.id === stepId);
            target.team = team;
          } else {
            const at = flow.steps.findIndex((s) => s.task !== 'team_setup');
            const newStep = { task: 'team_setup', mode: 'team', team, patch: {}, enabled: true, account: null };
            if (at < 0) flow.steps.push(newStep);
            else flow.steps.splice(at, 0, newStep);
          }
          await saveFlow(flow);
          closeDrawer();
        }, 'primary'),
      ],
    });
  }

  function stepSummary(flow, step) {
    if (step.task === 'custom_click') {
      const p = state.customPlans.find((x) => x.id === step.plan_id);
      return p ? [`方案 ${p.name}`, `${ccPlanModes(p)} · 超时 ${p.timeout}s`]
        : ['方案已删除，请点齿轮重新选择'];
    }
    const patch = step.patch || {};
    const acct = (step.account || flow.accounts[0]) || '';
    const inst = instOf(acct);
    const out = [];
    Object.entries(patch).forEach(([section, fields]) => {
      if (!fields || typeof fields !== 'object') return;
      ['layer', 'kirin_type', 'limit_count', 'boss_number', 'challenge_count'].forEach((k) => {
        if (k in fields) out.push(`${labelOf(k)} ${fields[k]}`);
      });
      if (fields.preset_enable) out.push(`预设 ${fields.preset_group || 1}-${fields.preset_team || 1}`);
      if (fields.user_status) out.push(fields.user_status === 'leader' ? '队长' : fields.user_status === 'member' ? '队员' : '单人');
    });
    if (!out.length && inst) {
      return [];
    }
    return out.slice(0, 4);
  }

  function labelOf(key) {
    return { layer: '层', kirin_type: '属性', limit_count: '次数', boss_number: '鬼王', challenge_count: '次数' }[key] || key;
  }

  /* ---------------- 自定义点击 ----------------
     控制台伪任务：方案存在 gui_custom_clicks.json，编排步骤只引用 plan_id。
     执行器 engine/gui/custom_click_runner.py 复用引擎 OCR + 矩形内拟人点击 + 随机延时。 */
  const CC_FULL = [0, 0, 1280, 720];
  // 内置参数：不暴露到 UI，保存时仍按后端字段写入，执行期照旧走引擎拟人化
  const CC_POLL = [0.3, 0.8];      // OCR 轮询间隔（秒，浮动）
  const CC_BEFORE = [0.2, 0.8];    // 点击前浮动延时（秒）
  const CC_DELAY = 1.0;            // 点击后延时基准（秒），保存时按 ±20% 展开
  const ccLines = (s) => String(s || '').split('\n').map((x) => x.trim()).filter(Boolean);
  const ccNum = (v, d) => { const n = parseFloat(v); return Number.isFinite(n) ? n : d; };
  const smallBtn = (label, ico, fn, kind) => {
    const b = btn(label, ico, fn, kind); b.classList.add('btn-sm'); return b;
  };
  // 层级内循环：once 单次 / count 指定次数 / forever 手动停止；gap 为两轮间隔秒数
  function ccRepeat(raw) {
    const r = (raw && typeof raw === 'object') ? raw : {};
    const mode = ['once', 'count', 'forever'].includes(r.mode) ? r.mode : 'once';
    return {
      mode,
      count: Math.max(1, Math.min(parseInt(r.count, 10) || 2, 999)),
      gap: Math.max(0, Math.min(ccNum(r.gap, 1), 300)),
      recheck: r.recheck !== false,
    };
  }
  // 滚动寻找并点击的参数；缺省值与执行器 engine/gui/custom_click_runner.py 的 as_scroll 保持一致
  function ccScroll(raw) {
    const r = (raw && typeof raw === 'object') ? raw : {};
    const a = Array.isArray(r.anchor) && r.anchor.length === 2 ? r.anchor : [640, 400];
    const cl = (v, lo, hi, d) => Math.max(lo, Math.min(ccNum(v, d), hi));
    const rr = Array.isArray(r.template_rect) && r.template_rect.length === 4
      ? r.template_rect.map((n) => Math.round(ccNum(n, 0))) : [];
    return {
      anchor: [Math.round(cl(a[0], 0, 1279, 640)), Math.round(cl(a[1], 0, 719, 400))],
      direction: r.direction === 'up' ? 'up' : 'down',
      wheel: Math.round(cl(r.wheel, 1, 30, 5)),
      interval: Math.round(cl(r.interval, 0.2, 5, 0.8) * 100) / 100,
      timeout: Math.round(cl(r.timeout, 1, 120, 15)),
      threshold: Math.round(cl(r.threshold, 0.5, 0.99, 0.8) * 100) / 100,
      method: ['auto', 'wheel', 'drag'].includes(r.method) ? r.method : 'auto',
      template: typeof r.template === 'string' ? r.template : '',
      template_rect: rr,
    };
  }
  function newCCStep(i) {
    return {
      id: 'cs' + Math.random().toString(36).slice(2, 8), name: `第 ${i + 1} 层`,
      mode: 'direct', scroll: ccScroll(null),
      texts: [], forbid: [], match: 'all', ocr_roi: CC_FULL.slice(),
      rect: [400, 250, 880, 520], score: 0.6,
      delay_before: CC_BEFORE.slice(), delay_after: [0.8, 1.2], delay: CC_DELAY,
      repeat: ccRepeat(null), jump: 0,
    };
  }
  function newCCPlan() {
    return { id: null, name: '新方案', timeout: 30, poll: CC_POLL.slice(),
      battle: true, steps: [newCCStep(0)], updated: '' };
  }
  function ccDraft(raw) {
    const p = raw ? JSON.parse(JSON.stringify(raw)) : newCCPlan();
    p.timeout = Math.max(1, Math.round(ccNum(p.timeout, 30)));
    p.poll = CC_POLL.slice();  // 轮询间隔内置，旧方案一并归一
    p.battle = p.battle !== false;  // 旧方案默认开启全局战斗接管
    p.steps = (p.steps || []).map((s, i) => {
      const after = (s.delay_after && s.delay_after.length === 2)
        ? s.delay_after.map((n) => ccNum(n, CC_DELAY)) : [0.8, 1.2];
      const step = Object.assign(newCCStep(i), s, {
        mode: s.mode === 'scroll' ? 'scroll' : 'direct',
        scroll: ccScroll(s.scroll),
        forbid: [], ocr_roi: CC_FULL.slice(), rect: (s.rect || CC_FULL).slice(),
        delay_before: CC_BEFORE.slice(), delay_after: after.slice(),
        delay: Math.round(ccNum(s.delay, (after[0] + after[1]) / 2) * 10) / 10,
        texts: s.texts || [], repeat: ccRepeat(s.repeat),
        jump: Math.max(0, parseInt(s.jump, 10) || 0),
      });
      delete step.__image;  // 截图与目标图片缓存只属于编辑期
      delete step.__inst;
      delete step.__anchorImg;
      delete step.__tplImg;
      return step;
    });
    if (!p.steps.length) p.steps = [newCCStep(0)];
    p.steps.forEach((s) => { if (s.jump > p.steps.length) s.jump = 0; });
    return p;
  }
  // 保存前剔除编辑期截图与 UI 专用的 delay 单值，补回后端需要的固定字段。
  function ccPayload(draft) {
    return Object.assign({}, draft, {
      poll: CC_POLL.slice(),
      steps: draft.steps.map((s) => {
        const d = Math.max(0, Math.min(60, ccNum(s.delay, CC_DELAY)));
        const step = Object.assign({}, s, {
          mode: s.mode === 'scroll' ? 'scroll' : 'direct',
          scroll: ccScroll(s.scroll),
          forbid: [], ocr_roi: CC_FULL.slice(), delay_before: CC_BEFORE.slice(),
          delay_after: [Math.round(d * 0.8 * 100) / 100, Math.round(d * 1.2 * 100) / 100],
          repeat: ccRepeat(s.repeat),
          jump: Math.max(0, Math.min(parseInt(s.jump, 10) || 0, draft.steps.length)),
        });
        delete step.__image;
        delete step.__inst;
        delete step.__anchorImg;
        delete step.__tplImg;
        delete step.delay;
        return step;
      }),
    });
  }

  async function loadCustomPlans() {
    try {
      const data = await api('/api/custom-clicks');
      state.customPlans = data.plans || [];
    } catch (e) { state.customPlans = []; }  // 旧版 bridge 没有该接口时不影响其它页面
  }

  // 方案摘要：层数 + 其中几层是「滚动寻找并点击」
  function ccPlanModes(plan) {
    const steps = plan.steps || [];
    const scroll = steps.filter((s) => s.mode === 'scroll').length;
    return scroll ? `${steps.length} 层（滚动找图 ${scroll}）` : `${steps.length} 层`;
  }

  async function addCCStepToFlow(plan) {
    const flow = currentFlow();
    if (!flow) return toast('请先选中一份编排', 'err');
    flow.steps = flow.steps.concat([{
      task: 'custom_click', mode: 'solo', enabled: true, patch: {}, note: '',
      account: null, participants: [], team: {},
      plan_id: plan.id, plan_name: plan.name,
    }]);
    await saveFlow(flow, true);
    // silent 保存不会重绘；这里必须手动 render，否则步骤列表看不见新加的一层
    render();
  }

  function openCustomClickLibrary(opts) {
    const forStep = opts && opts.forStep;
    const body = el('div');
    const list = el('div', { class: 'grid grid-2', style: 'margin-top:10px' });
    function paint() {
      list.innerHTML = '';
      if (!state.customPlans.length) {
        list.appendChild(el('div', { class: 'empty', style: 'grid-column:1/-1' },
          el('strong', { text: '还没有方案' }), el('p', { text: '点右下角「新建方案」开始配置。' })));
      }
      state.customPlans.forEach((p) => {
        const ops = el('div', { class: 'tc-ops' });
        if (forStep) {
          ops.appendChild(smallBtn('选用', 'check', async () => {
            const flow = currentFlow();
            const s = flow && flow.steps.find((x) => x.id === forStep);
            if (!s) return;
            s.plan_id = p.id; s.plan_name = p.name;
            await saveFlow(flow, true);
            closeDrawer(); render(); toast('已切换方案', 'ok');
          }, 'primary'));
        } else {
          ops.appendChild(smallBtn('加到编排', 'plus', async () => {
            try { await addCCStepToFlow(p); closeDrawer(); toast('已加入编排', 'ok'); }
            catch (e) { toast('添加失败：' + e.message, 'err'); }
          }, 'primary'));
        }
        ops.appendChild(smallBtn('编辑', 'cog', () => openCustomClickEditor(p.id, false), 'ghost'));
        ops.appendChild(smallBtn('复制', 'copy', async () => {
          try { await api(`/api/custom-clicks/${p.id}/duplicate`, { method: 'POST' }); await loadCustomPlans(); paint(); }
          catch (e) { toast('复制失败：' + e.message, 'err'); }
        }, 'ghost'));
        ops.appendChild(smallBtn('删除', 'trash', async () => {
          if (!confirm(`删除方案「${p.name}」？`)) return;
          try { await api(`/api/custom-clicks/${p.id}`, { method: 'DELETE' }); await loadCustomPlans(); paint(); }
          catch (e) { toast('删除失败：' + e.message, 'err'); }
        }, 'danger'));
        list.appendChild(el('div', { class: 'task-card' },
          el('div', { class: 'tc-top' },
            el('span', { class: 'tc-name', text: p.name }),
            el('span', { class: 'badge badge-dim', text: '方案' })),
          el('div', { class: 'tc-desc', text: `${ccPlanModes(p)} · 超时 ${p.timeout}s` }),
          ops));
      });
    }
    paint();
    body.appendChild(list);
    openDrawer({
      kicker: '自定义点击', title: forStep ? '更换方案' : '方案库', body,
      foot: [btn('新建方案', 'plus', () => openCustomClickEditor(null, !forStep), 'primary'),
        btn('关闭', 'x', closeDrawer, 'ghost')],
    });
  }

  function openCustomClickEditor(planId, autoAdd) {
    const flow = currentFlow();
    if (!flow) return toast('请先选中一份编排', 'err');
    const src = state.customPlans.find((p) => p.id === planId);
    const draft = ccDraft(src);
    const insts = state.instances.length ? state.instances : [];
    let lastCapInst = insts.length ? insts[0].name : '';
    const body = el('div');

    const nameInput = el('input', { class: 'input', value: draft.name });
    nameInput.addEventListener('input', () => { draft.name = nameInput.value.trim() || '未命名方案'; });
    const timeoutInput = el('input', { class: 'input', type: 'number', min: '1', max: '3600', value: String(draft.timeout) });
    timeoutInput.addEventListener('input', () => { draft.timeout = Math.max(1, parseInt(timeoutInput.value, 10) || 30); });
    body.append(el('div', { class: 'cc-grid' },
      field('方案名称', nameInput),
      field('等待超时（秒）', timeoutInput)));
    const battleChk = el('input', { type: 'checkbox', checked: draft.battle });
    battleChk.addEventListener('change', () => { draft.battle = battleChk.checked; });
    body.append(el('label', {
      class: 'cc-check cc-plan-check',
      title: '等待文字时检测战斗准备 / 战斗中 / 胜利结算，交给引擎跑完整场战斗，完成后回到本层继续判定',
    }, battleChk, el('span', { text: '自动接管战斗' })));

    const stepsBox = el('div', { class: 'cc-steps' });
    body.append(el('div', { class: 'section-title' },
      el('h2', { text: '层级' }),
      el('span', { class: 'sub', text: '按顺序执行' })), stepsBox);

    // 每层的大图就是选区画布：抓图后直接在图上拖框，框即点击区域
    function captureBlock(step) {
      const instSel = el('select', { class: 'select' });
      insts.forEach((n) => instSel.appendChild(el('option', { value: n.name, text: n.nickname || n.name })));
      if (step.__inst || lastCapInst) instSel.value = step.__inst || lastCapInst;
      const capNote = el('span', { class: 'small muted',
        text: step.__image ? '在图上拖框选出点击区域（可重拖）' : '抓取画面后，在图上拖框选出点击区域' });

      const stage = el('div', { class: 'cc-stage' + (step.__image ? '' : ' empty') });
      const img = el('img', { class: 'cc-stage-img', src: step.__image || '', alt: '本层画面' });
      const sel = el('div', { class: 'cc-sel' });
      const empty = el('div', { class: 'cc-stage-empty', text: '抓取本层画面后，在图上拖框选出点击区域' });
      img.hidden = !step.__image; empty.hidden = !!step.__image; sel.hidden = !step.__image;
      stage.append(img, sel, empty);

      const put = (r) => {
        sel.style.left = (r[0] / 1280 * 100) + '%';
        sel.style.top = (r[1] / 720 * 100) + '%';
        sel.style.width = ((r[2] - r[0]) / 1280 * 100) + '%';
        sel.style.height = ((r[3] - r[1]) / 720 * 100) + '%';
      };
      const coord = (e) => {
        const b = img.getBoundingClientRect();
        return [Math.max(0, Math.min(1280, Math.round((e.clientX - b.left) * 1280 / b.width))),
          Math.max(0, Math.min(720, Math.round((e.clientY - b.top) * 720 / b.height)))];
      };
      const between = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]),
        Math.max(a[0], b[0]), Math.max(a[1], b[1])];
      let origin = null, dragging = false;
      stage.addEventListener('pointerdown', (e) => {
        if (!step.__image) return;
        dragging = true; origin = coord(e);
        put([origin[0], origin[1], origin[0], origin[1]]);
        try { stage.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
        e.preventDefault();
      });
      stage.addEventListener('pointermove', (e) => {
        if (dragging) put(between(origin, coord(e)));
      });
      stage.addEventListener('pointerup', (e) => {
        if (!dragging) return;
        dragging = false;
        const r = between(origin, coord(e));
        if (r[2] - r[0] < 8 || r[3] - r[1] < 8) { put(step.rect); return; }
        step.rect = r; put(r); capNote.textContent = '点击区域已设定';
      });
      put(step.rect);

      const capBtn = smallBtn('抓取本层画面', 'refresh', async () => {
        if (!instSel.value) return toast('请先绑定模拟器', 'err');
        capBtn.disabled = true; capNote.textContent = '抓取中…';
        try {
          const r = await api(`/api/instances/${encodeURIComponent(instSel.value)}/screenshot`, { method: 'POST' });
          step.__image = r.image; step.__inst = instSel.value; lastCapInst = instSel.value;
          img.src = r.image; img.hidden = false; empty.hidden = true; sel.hidden = false;
          stage.classList.remove('empty');
          put(step.rect);
          capNote.textContent = '在图上拖框选出点击区域（可重拖）';
        } catch (e) { capNote.textContent = '抓取失败：' + e.message; toast('抓取失败：' + e.message, 'err'); }
        capBtn.disabled = false;
      }, 'ghost');

      return el('div', { class: 'cc-cap' },
        el('div', { class: 'row cc-cap-tools' }, instSel, capBtn, capNote), stage);
    }

    // 抓图与裁剪：滚动层的目标图片直接从第二张截图里裁出来，以 base64 PNG 存进方案
    async function ccGrab(instName) {
      const r = await api(`/api/instances/${encodeURIComponent(instName)}/screenshot`, { method: 'POST' });
      return r.image;
    }
    const ccImageCache = new Map();
    function ccLoadImage(src) {
      if (ccImageCache.has(src)) return Promise.resolve(ccImageCache.get(src));
      return new Promise((resolve, reject) => {
        const im = new Image();
        im.onload = () => { ccImageCache.set(src, im); resolve(im); };
        im.onerror = () => reject(new Error('画面解码失败'));
        im.src = src;
      });
    }
    async function ccCrop(dataUrl, rect) {
      const im = await ccLoadImage(dataUrl);
      const w = Math.max(1, rect[2] - rect[0]), h = Math.max(1, rect[3] - rect[1]);
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      c.getContext('2d').drawImage(im, rect[0], rect[1], w, h, 0, 0, w, h);
      return c.toDataURL('image/png').split(',')[1];
    }

    // 滚动层 ①：抓图后单击图上任意一点，作为鼠标停留位置（滚轮就在这里滚）
    function anchorBlock(step) {
      const instSel = el('select', { class: 'select' });
      insts.forEach((n) => instSel.appendChild(el('option', { value: n.name, text: n.nickname || n.name })));
      if (step.__inst || lastCapInst) instSel.value = step.__inst || lastCapInst;
      const note = el('span', { class: 'small muted',
        text: step.__anchorImg ? '在图上单击，设定鼠标停留点' : '抓取画面后，在图上单击设定鼠标停留点' });
      const stage = el('div', { class: 'cc-stage' + (step.__anchorImg ? '' : ' empty') });
      const img = el('img', { class: 'cc-stage-img', src: step.__anchorImg || '', alt: '鼠标位置参考画面' });
      const dot = el('div', { class: 'cc-anchor' });
      const empty = el('div', { class: 'cc-stage-empty', text: '抓取画面后，在图上单击设定鼠标停留点' });
      img.hidden = !step.__anchorImg; empty.hidden = !!step.__anchorImg; dot.hidden = !step.__anchorImg;
      stage.append(img, dot, empty);
      const put = (p) => { dot.style.left = (p[0] / 1280 * 100) + '%'; dot.style.top = (p[1] / 720 * 100) + '%'; };
      const coord = (e) => {
        const b = img.getBoundingClientRect();
        return [Math.max(0, Math.min(1280, Math.round((e.clientX - b.left) * 1280 / b.width))),
          Math.max(0, Math.min(720, Math.round((e.clientY - b.top) * 720 / b.height)))];
      };
      stage.addEventListener('pointerdown', (e) => {
        if (!step.__anchorImg) return;
        const p = coord(e);
        step.scroll.anchor = p; put(p); dot.hidden = false;
        note.textContent = `鼠标停留点 (${p[0]}, ${p[1]})`;
        e.preventDefault();
      });
      put(step.scroll.anchor);
      const capBtn = smallBtn('抓取画面', 'refresh', async () => {
        if (!instSel.value) return toast('请先绑定模拟器', 'err');
        capBtn.disabled = true; note.textContent = '抓取中…';
        try {
          const src = await ccGrab(instSel.value);
          step.__anchorImg = src; step.__inst = instSel.value; lastCapInst = instSel.value;
          img.src = src; img.hidden = false; empty.hidden = true; dot.hidden = false;
          stage.classList.remove('empty');
          put(step.scroll.anchor);
          note.textContent = '在图上单击，设定鼠标停留点';
        } catch (e) { note.textContent = '抓取失败：' + e.message; toast('抓取失败：' + e.message, 'err'); }
        capBtn.disabled = false;
      }, 'ghost');
      return el('div', { class: 'cc-cap' },
        el('div', { class: 'row cc-cap-tools' }, instSel, capBtn, note), stage);
    }

    // 滚动层 ②：再抓一张画面，框选出要找的目标图案（裁剪后作为匹配模板）
    function targetBlock(step) {
      const instSel = el('select', { class: 'select' });
      insts.forEach((n) => instSel.appendChild(el('option', { value: n.name, text: n.nickname || n.name })));
      if (step.__inst || lastCapInst) instSel.value = step.__inst || lastCapInst;
      const note = el('span', { class: 'small muted',
        text: step.__tplImg ? '在图上拖框，框出要找的目标图案（可重拖）' : '抓取画面后，在图上拖框框出目标图案' });
      const stage = el('div', { class: 'cc-stage' + (step.__tplImg ? '' : ' empty') });
      const img = el('img', { class: 'cc-stage-img', src: step.__tplImg || '', alt: '目标图案参考画面' });
      const sel = el('div', { class: 'cc-sel' });
      const empty = el('div', { class: 'cc-stage-empty', text: '抓取画面后，在图上拖框框出目标图案' });
      const preview = el('div', { class: 'cc-tpl' });
      function paintPreview() {
        preview.innerHTML = '';
        if (!step.scroll.template) {
          preview.appendChild(el('span', { class: 'small muted', text: '目标图片：未设置' }));
          return;
        }
        preview.append(
          el('img', { class: 'cc-tpl-img', src: 'data:image/png;base64,' + step.scroll.template, alt: '目标图片' }),
          el('span', { class: 'small muted', text: '目标图片已设置，执行时按它匹配' }));
      }
      img.hidden = !step.__tplImg; empty.hidden = !!step.__tplImg; sel.hidden = !step.__tplImg;
      stage.append(img, sel, empty);
      const put = (r) => {
        sel.style.left = (r[0] / 1280 * 100) + '%';
        sel.style.top = (r[1] / 720 * 100) + '%';
        sel.style.width = ((r[2] - r[0]) / 1280 * 100) + '%';
        sel.style.height = ((r[3] - r[1]) / 720 * 100) + '%';
      };
      const coord = (e) => {
        const b = img.getBoundingClientRect();
        return [Math.max(0, Math.min(1280, Math.round((e.clientX - b.left) * 1280 / b.width))),
          Math.max(0, Math.min(720, Math.round((e.clientY - b.top) * 720 / b.height)))];
      };
      const between = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]),
        Math.max(a[0], b[0]), Math.max(a[1], b[1])];
      let origin = null, dragging = false;
      stage.addEventListener('pointerdown', (e) => {
        if (!step.__tplImg) return;
        dragging = true; origin = coord(e);
        put([origin[0], origin[1], origin[0], origin[1]]);
        try { stage.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
        e.preventDefault();
      });
      stage.addEventListener('pointermove', (e) => { if (dragging) put(between(origin, coord(e))); });
      stage.addEventListener('pointerup', async (e) => {
        if (!dragging) return;
        dragging = false;
        const r = between(origin, coord(e));
        if (r[2] - r[0] < 8 || r[3] - r[1] < 8) { put(step.scroll.template_rect || [0, 0, 0, 0]); return; }
        step.scroll.template_rect = r; put(r);
        note.textContent = '裁剪中…';
        try {
          step.scroll.template = await ccCrop(step.__tplImg, r);
          paintPreview();
          note.textContent = `目标图案已截取 ${r[2] - r[0]}×${r[3] - r[1]}（可重拖）`;
        } catch (err) { note.textContent = '裁剪失败：' + err.message; }
      });
      if (step.scroll.template_rect && step.scroll.template_rect.length === 4) put(step.scroll.template_rect);
      paintPreview();
      const capBtn = smallBtn('抓取画面', 'refresh', async () => {
        if (!instSel.value) return toast('请先绑定模拟器', 'err');
        capBtn.disabled = true; note.textContent = '抓取中…';
        try {
          const src = await ccGrab(instSel.value);
          step.__tplImg = src; step.__inst = instSel.value; lastCapInst = instSel.value;
          img.src = src; img.hidden = false; empty.hidden = true; sel.hidden = false;
          stage.classList.remove('empty');
          if (step.scroll.template_rect && step.scroll.template_rect.length === 4) put(step.scroll.template_rect);
          note.textContent = '在图上拖框，框出要找的目标图案（可重拖）';
        } catch (e) { note.textContent = '抓取失败：' + e.message; toast('抓取失败：' + e.message, 'err'); }
        capBtn.disabled = false;
      }, 'ghost');
      return el('div', { class: 'cc-cap' },
        el('div', { class: 'row cc-cap-tools' }, instSel, capBtn, note), stage, preview);
    }

    function stepCard(step, i) {
      const card = el('div', { class: 'panel cc-step' });
      const nameInp = el('input', { class: 'input cc-name', value: step.name || '' });
      nameInp.addEventListener('input', () => { step.name = nameInp.value.trim() || `第 ${i + 1} 层`; });
      const head = el('div', { class: 'cc-step-head' },
        el('strong', { text: `第 ${i + 1} 层` }), nameInp, el('span', { class: 'grow' }),
        smallBtn('删除', 'trash', () => { draft.steps.splice(i, 1); paintSteps(); }, 'danger'));

      const textTa = el('textarea', { class: 'textarea', rows: '2', placeholder: '每行一个关键词，例：探索' });
      textTa.value = (step.texts || []).join('\n');
      textTa.addEventListener('input', () => { step.texts = ccLines(textTa.value); });
      const matchSel = el('select', { class: 'select' },
        el('option', { value: 'all', text: '全部命中' }),
        el('option', { value: 'any', text: '命中任意' }));
      matchSel.value = step.match === 'any' ? 'any' : 'all';
      matchSel.addEventListener('change', () => { step.match = matchSel.value; });
      const scoreInp = el('input', { class: 'input', type: 'number', min: '0.1', max: '1', step: '0.05', value: String(step.score) });
      scoreInp.addEventListener('input', () => { step.score = Math.max(0.1, Math.min(1, ccNum(scoreInp.value, 0.6))); });
      const delayInp = el('input', { class: 'input', type: 'number', min: '0', max: '60', step: '0.1', value: String(step.delay) });
      delayInp.addEventListener('input', () => { step.delay = Math.max(0, Math.min(60, ccNum(delayInp.value, CC_DELAY))); });

      const rep = step.repeat;
      const repSel = el('select', { class: 'select' },
        el('option', { value: 'once', text: '仅一次' }),
        el('option', { value: 'count', text: '重复 N 次' }),
        el('option', { value: 'forever', text: '一直循环（手动停止）' }));
      repSel.value = rep.mode;
      const countInp = el('input', { class: 'input', type: 'number', min: '1', max: '999', value: String(rep.count) });
      countInp.addEventListener('input', () => { rep.count = Math.max(1, Math.min(parseInt(countInp.value, 10) || 2, 999)); });
      const gapInp = el('input', { class: 'input', type: 'number', min: '0', max: '300', step: '0.1', value: String(rep.gap) });
      gapInp.addEventListener('input', () => { rep.gap = Math.max(0, Math.min(300, ccNum(gapInp.value, 1))); });
      const recheckChk = el('input', { type: 'checkbox', checked: rep.recheck });
      recheckChk.addEventListener('change', () => { rep.recheck = recheckChk.checked; });
      const recheckBox = el('label', { class: 'cc-check' }, recheckChk,
        el('span', { text: '每轮重新检测文字' }));
      const countField = field('重复次数', countInp);
      const paintRep = () => { countField.hidden = repSel.value !== 'count'; };
      repSel.addEventListener('change', () => { rep.mode = repSel.value; paintRep(); });
      paintRep();

      // 本层跑完后可跳回任意层（默认不跳转）；目标层号随层数变化自动收敛
      const jumpSel = el('select', { class: 'select' });
      jumpSel.appendChild(el('option', { value: '0', text: '不跳转' }));
      draft.steps.forEach((s, k) => {
        jumpSel.appendChild(el('option', { value: String(k + 1), text: `第 ${k + 1} 层 · ${s.name || ''}` }));
      });
      step.jump = (step.jump >= 1 && step.jump <= draft.steps.length) ? step.jump : 0;
      jumpSel.value = String(step.jump);
      jumpSel.addEventListener('change', () => { step.jump = parseInt(jumpSel.value, 10) || 0; });

      // 动作类型：直接识别并点击（OCR）/ 滚动寻找并点击（图片匹配）
      const modeSel = el('select', { class: 'select' },
        el('option', { value: 'direct', text: '直接识别并点击（看文字）' }),
        el('option', { value: 'scroll', text: '滚动寻找并点击（找图片）' }));
      modeSel.value = step.mode === 'scroll' ? 'scroll' : 'direct';
      modeSel.addEventListener('change', () => { step.mode = modeSel.value; paintSteps(); });

      // 滚动层参数：鼠标停留点由 ① 点击确定，目标图片由 ② 框选确定
      const sc = step.scroll;
      const scMethodSel = el('select', { class: 'select' },
        el('option', { value: 'auto', text: '自动（优先滚轮）' }),
        el('option', { value: 'wheel', text: '鼠标滚轮' }),
        el('option', { value: 'drag', text: '手指拖动' }));
      scMethodSel.value = sc.method;
      scMethodSel.addEventListener('change', () => { sc.method = scMethodSel.value; });
      const scDirectionSel = el('select', { class: 'select' },
        el('option', { value: 'down', text: '向下滚动' }),
        el('option', { value: 'up', text: '向上滚动' }));
      scDirectionSel.value = sc.direction;
      scDirectionSel.addEventListener('change', () => { sc.direction = scDirectionSel.value; });
      const scWheelInp = el('input', { class: 'input', type: 'number', min: '1', max: '30', value: String(sc.wheel) });
      scWheelInp.addEventListener('input', () => { sc.wheel = Math.round(Math.max(1, Math.min(ccNum(scWheelInp.value, 5), 30))); });
      const scIntervalInp = el('input', { class: 'input', type: 'number', min: '0.2', max: '5', step: '0.1', value: String(sc.interval) });
      scIntervalInp.addEventListener('input', () => { sc.interval = Math.round(Math.max(0.2, Math.min(ccNum(scIntervalInp.value, 0.8), 5)) * 100) / 100; });
      const scScoreInp = el('input', { class: 'input', type: 'number', min: '0.5', max: '0.99', step: '0.01', value: String(sc.threshold) });
      scScoreInp.addEventListener('input', () => { sc.threshold = Math.round(Math.max(0.5, Math.min(ccNum(scScoreInp.value, 0.8), 0.99)) * 100) / 100; });
      const scTimeoutInp = el('input', { class: 'input', type: 'number', min: '1', max: '120', value: String(sc.timeout) });
      scTimeoutInp.addEventListener('input', () => { sc.timeout = Math.round(Math.max(1, Math.min(ccNum(scTimeoutInp.value, 15), 120))); });

      const body = el('div', { class: 'panel-body' }, field('动作类型', modeSel));
      if (step.mode === 'scroll') {
        body.append(
          el('div', { class: 'cc-hint', text: '① 抓图后单击图上任意位置 = 鼠标停留点；② 再抓一张画面，框选要点击的目标图案。执行时一边滚动一边找，找到就点它。滚动方式选「自动」时，能把滚轮发进模拟器就用滚轮，否则自动改成手指拖动（adb/minitouch 控制方式一般走拖动）。' }),
          anchorBlock(step),
          targetBlock(step),
          el('div', { class: 'cc-grid cc-grid-3' },
            field('滚动方式', scMethodSel), field('滚动方向', scDirectionSel), field('每次滚动格数', scWheelInp)),
          el('div', { class: 'cc-grid cc-grid-3' },
            field('滚动间隔（秒）', scIntervalInp), field('目标匹配度', scScoreInp), field('寻找超时（秒）', scTimeoutInp)));
      } else {
        body.append(
          captureBlock(step),
          field('判定文字（每行一条 · 检测到才点击）', textTa),
          el('div', { class: 'cc-grid cc-grid-3' },
            field('匹配', matchSel), field('置信度', scoreInp)));
      }
      body.append(
        field('点击后延时（秒）', delayInp),
        el('div', { class: 'cc-grid cc-grid-3' },
          field('本层重复', repSel), countField, field('循环间隔（秒）', gapInp)));
      if (step.mode !== 'scroll') body.append(recheckBox);
      body.append(field('执行后跳转', jumpSel));
      card.append(head, body);
      return card;
    }
    function paintSteps() {
      stepsBox.innerHTML = '';
      draft.steps.forEach((s, i) => stepsBox.appendChild(stepCard(s, i)));
    }
    paintSteps();
    body.appendChild(el('div', { style: 'margin-top:10px' },
      smallBtn('追加一层', 'plus', () => { draft.steps.push(newCCStep(draft.steps.length)); paintSteps(); }, 'ghost')));

    openDrawer({
      kicker: '自定义点击', title: src ? `编辑方案 · ${src.name}` : '新建方案', body,
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存方案', 'check', async () => {
          if (!draft.steps.length) return toast('至少保留一层', 'err');
          try {
            const payload = ccPayload(draft);
            const r = src
              ? await api(`/api/custom-clicks/${src.id}`, { method: 'PUT', body: payload })
              : await api('/api/custom-clicks', { method: 'POST', body: payload });
            await loadCustomPlans();
            let note = autoAdd ? '方案已保存并加入编排' : '方案已保存';
            if (autoAdd) {
              try { await addCCStepToFlow(r.plan); }
              catch (e) { note = '方案已保存，但加入编排失败：' + e.message; }
            }
            closeDrawer();
            render();
            toast(note, 'ok');
          } catch (e) { toast('保存失败：' + e.message, 'err'); }
        }, 'primary'),
      ],
    });
  }

  /* ---- 编排 CRUD ---- */
  function openNewFlowDrawer(account) {
    const nameInput = el('input', { class: 'input', placeholder: '如：日常一条龙 / 双开御魂' });
    const ordered = state.instances.slice().sort((a, b) => (b.primary ? 1 : 0) - (a.primary ? 1 : 0));
    let accounts = [account || (ordered.length ? ordered[0].name : '')].filter(Boolean);
    const chips = el('div', { class: 'chips' });
    function paintChips() {
      chips.innerHTML = '';
      ordered.forEach((inst) => {
        const on = accounts.includes(inst.name);
        const chip = el('button', { class: 'chip' + (on ? ' active' : ''), text: inst.nickname || inst.name });
        chip.addEventListener('click', () => {
          if (on) accounts = accounts.filter((a) => a !== inst.name);
          else accounts = accounts.concat(inst.name);
          paintChips();
        });
        chips.appendChild(chip);
      });
    }
    paintChips();

    const body = el('div', {},
      field('编排表名称', nameInput),
      el('div', { class: 'field' }, el('label', { text: '绑定账号（第一个为队长；多开可绑定任意多个）' }), chips),
      el('p', { class: 'hint', text: '创建后在编辑页逐个添加任务即可。' }),
    );

    let tplSelect = null;
    if (state.flowLib.length) {
      tplSelect = el('select', { class: 'input' });
      tplSelect.appendChild(el('option', { value: '', text: '空白编排' }));
      state.flowLib.forEach((t) => tplSelect.appendChild(el('option', { value: t.id, text: t.name })));
      body.appendChild(field('从自定义方案创建', tplSelect));
    }

    openDrawer({
      kicker: '任务编排',
      title: '新建编排表',
      body,
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('创建', 'plus', async () => {
          const name = nameInput.value.trim() || '未命名编排';
          if (!accounts.length) return toast('请先绑定账号', 'err');
          let steps = [];
          const tpl = tplSelect && state.flowLib.find((t) => t.id === tplSelect.value);
          if (tpl) {
            steps = withTeamStep(tpl.steps.map((s) => ({
              task: s.task, mode: (s.mode === 'team' || s.mode === 'duo') ? 'team' : 'solo',
              patch: s.patch || {}, note: s.note || '', enabled: s.enabled !== false,
              plan_id: s.plan_id || null, plan_name: s.plan_name || '',
            })), accounts);
          }
          try {
            const r = await api('/api/flows', { method: 'POST', body: { name, accounts, steps } });
            state.flowId = r.flow.id;
            await loadFlows();
            closeDrawer();
            go('flows');
            toast(tpl ? '编排已按方案创建' : '编排已创建', 'ok');
          } catch (e) { toast('创建失败：' + e.message, 'err'); }
        }, 'primary'),
      ],
    });
  }

  function withTeamStep(steps, accounts) {
    const needsTeam = steps.some((s) => s.mode === 'team' || s.mode === 'duo');
    if (!needsTeam || accounts.length < 2) return steps;
    return [{ task: 'team_setup', mode: 'team', enabled: true,
      team: { leader: accounts[0], members: accounts.slice(1) } }].concat(steps);
  }

  function openFlowBindDrawer(flow) {
    let accounts = flow.accounts.slice();
    const chips = el('div', { class: 'chips' });
    const ordered = state.instances.slice().sort((a, b) => (b.primary ? 1 : 0) - (a.primary ? 1 : 0));
    function paint() {
      chips.innerHTML = '';
      ordered.forEach((inst) => {
        const on = accounts.includes(inst.name);
        const chip = el('button', { class: 'chip' + (on ? ' active' : ''), text: inst.nickname || inst.name });
        chip.addEventListener('click', () => {
          if (on) accounts = accounts.filter((a) => a !== inst.name);
          else accounts = accounts.concat(inst.name);
          paint();
        });
        chips.appendChild(chip);
      });
    }
    paint();
    openDrawer({
      kicker: '任务编排',
      title: '绑定账号',
      body: el('div', {},
        el('div', { class: 'field' }, el('label', { text: '账号（顺序即队长 → 队员；点选可增减）' }), chips),
        el('p', { class: 'hint', text: '第一个账号作为队长端，其余为队员端。删除账号后，指向它的联动步骤会在账号不足 2 个时自动降级为单人。' }),
      ),
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => {
          if (!accounts.length) return toast('至少保留一个账号', 'err');
          const steps = flow.steps.map((s) => {
            const patch = Object.assign({}, s, { mode: s.mode === 'team' && accounts.length < 2 ? 'solo' : s.mode });
            if (patch.account && !accounts.includes(patch.account)) patch.account = null;
            return patch;
          });
          await saveFlow(Object.assign({}, flow, { accounts, steps }));
          closeDrawer();
        }, 'primary'),
      ],
    });
  }

  async function saveFlow(flow, silent) {
    try {
      const r = await api(`/api/flows/${flow.id}`, {
        method: 'PUT',
        body: { name: flow.name, accounts: flow.accounts, steps: flow.steps,
          loop: normalizeLoop(flow.loop), idle: normalizeIdle(flow.idle) },
      });
      await loadFlows();
      if (!silent) { render(); toast('已保存', 'ok'); }
      return r.flow;
    } catch (e) { toast('保存失败：' + e.message, 'err'); throw e; }
  }

  async function renameFlow(flow) {
    const input = el('input', { class: 'input', value: flow.name });
    openDrawer({
      kicker: '任务编排', title: '重命名', body: field('名称', input),
      foot: [btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => { await saveFlow(Object.assign({}, flow, { name: input.value.trim() || flow.name })); closeDrawer(); }, 'primary')],
    });
  }

  function saveFlowAsTemplate(flow) {
    if (!flow.steps.some((s) => s.task !== 'team_setup')) return toast('空编排没有可保存的步骤', 'warn');
    const nameInput = el('input', { class: 'input', value: flow.name });
    openDrawer({
      kicker: '自定义方案', title: '存为自定义方案',
      body: el('div', {},
        field('方案名称', nameInput),
        el('p', { class: 'hint', text: '方案只保留任务与参数，不含账号和模拟器，可长期复用。' }),
      ),
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => {
          try {
            await api('/api/flow-library', {
              method: 'POST',
              body: { name: nameInput.value.trim() || flow.name, flow_id: flow.id },
            });
            await loadFlowLib();
            closeDrawer();
            toast('已保存方案', 'ok');
          } catch (e) { toast('保存失败：' + e.message, 'err'); }
        }, 'primary'),
      ],
    });
  }

  async function deleteFlow(flow) {
    if (!confirm(`删除编排「${flow.name}」？`)) return;
    const owner = flowOwner(flow);
    await api(`/api/flows/${flow.id}`, { method: 'DELETE' });
    state.flowId = null;
    await loadFlows();
    // 同账号还有别的编排就接着看那一份，别让用户回到空状态。
    const sibling = state.flows.find((f) => flowOwner(f) === owner);
    if (sibling) state.flowId = sibling.id;
    render();
    toast('已删除', 'ok');
  }

  // 有作业在跑时把界面挂上去（打开日志坞 + watchJob），而不是只弹提示
  async function attachRunningJob(match) {
    try {
      await loadJobs();
      const runningJob = state.jobs.find((j) => j.status === 'running' && match(j));
      if (runningJob) {
        state.jobId = runningJob.id;
        state.flowId = runningJob.flow_id;
        dockReset(runningJob.id);
        dockSetOpen(true);
        watchJob(runningJob.id);
        render();
        return true;
      }
    } catch (e) { /* ignore */ }
    return false;
  }

  /* 循环设置控件：只在编排详情的「循环设置」抽屉里出现；点「执行」不再弹窗。 */
  function buildLoopControls(preset) {
    const p = normalizeLoop(preset);
    const modeSel = el('select', { class: 'select' },
      el('option', { value: 'once', text: '仅执行一次（跑完一遍就结束）' }),
      el('option', { value: 'count', text: '循环指定轮数' }),
      el('option', { value: 'forever', text: '一直循环（手动停止）' }));
    modeSel.value = p.mode;
    const countInput = el('input', { class: 'input', type: 'number', min: '2', max: '999',
      value: String(p.count || 2) });
    const countField = field('循环轮数', countInput, '整份编排从头到尾算一轮；可设 2–999 轮。');
    const intervalInput = el('input', { class: 'input', type: 'number', min: '0', max: '300',
      value: String(p.interval) });
    const onError = el('input', { type: 'checkbox', checked: p.on_error === 'continue' });
    const paint = () => { countField.hidden = modeSel.value !== 'count'; };
    modeSel.addEventListener('change', paint);
    paint();
    const node = el('div', {},
      field('执行方式', modeSel),
      countField,
      field('每轮间隔（秒）', intervalInput,
        '两轮之间留出结算/回庭院的时间，0 表示立刻开始下一轮。'),
      el('div', { class: 'field' }, el('label', { text: '失败处理' }),
        el('label', { class: 'switch' }, onError, el('span', { class: 'track' }),
          el('span', { class: 'small', text: '某轮失败时继续下一轮（默认失败即停止整份编排）' }))),
    );
    const read = () => ({
      mode: modeSel.value,
      count: parseInt(countInput.value, 10),
      interval: parseInt(intervalInput.value, 10),
      on_error: onError.checked ? 'continue' : 'stop',
    });
    return { node, read };
  }

  // 点「执行」直接开跑：循环次数 / 轮间隔 / 失败处理统一在「循环设置」里改，
  // 保存后即刻生效，不再弹执行确认框。
  function runFlow(flow) {
    if (!flow) return toast('请先选择编排', 'err');
    const id = flow.id;
    if (flowLocked(flow)) {
      toast('该账号正在执行其它编排', 'warn');
      attachRunningJob((j) => j.flow_id === id
        || (j.accounts || []).some((a) => flow.accounts.includes(a)));
      return;
    }
    return startFlow(flow, normalizeLoop(flow.loop), false);
  }

  function openLoopDrawer(flow) {
    const ctl = buildLoopControls(flow.loop);
    openDrawer({
      kicker: '任务编排', title: '循环设置',
      body: el('div', {},
        el('p', { class: 'hint', text: '这里设好就生效：点「执行」会直接按下面的方式开跑，不再弹窗确认。'
          + '「一直循环」只能在运行中手动点「停止」。' }),
        ctl.node,
      ),
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => {
          try { await saveFlow(Object.assign({}, flow, { loop: normalizeLoop(ctl.read()) })); }
          catch (e) { return; }
          closeDrawer();
        }, 'primary'),
      ],
    });
  }

  /* 随机发呆：任务执行前后 + 自定义点击每层循环前后，按概率静止不操作。 */
  function openIdleDrawer(flow) {
    const p = normalizeIdle(flow.idle);
    const on = el('input', { type: 'checkbox', checked: p.enable });
    const num = (v) => el('input', { class: 'input', type: 'number', min: '0', max: '600',
      step: '0.5', value: String(v) });
    const minInp = num(p.min), maxInp = num(p.max);
    const probInp = el('input', { class: 'input', type: 'number', min: '0', max: '100',
      step: '1', value: String(Math.round(p.probability * 100)) });
    const body = el('div', {},
      el('div', { class: 'field' }, el('label', { text: '启用' }),
        el('label', { class: 'switch' }, on, el('span', { class: 'track' }),
          el('span', { class: 'small', text: '任务执行前后、自定义点击每层循环前后，随机静止不操作' }))),
      el('div', { class: 'cc-grid' }, field('最短（秒）', minInp), field('最长（秒）', maxInp)),
      field('触发概率（%）', probInp, '每个判定点独立计算，0 表示不触发。'),
    );
    openDrawer({
      kicker: '任务编排', title: '随机发呆', body,
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => {
          const idle = normalizeIdle({
            enable: on.checked, min: minInp.value, max: maxInp.value,
            probability: (parseFloat(probInp.value) || 0) / 100,
          });
          try { await saveFlow(Object.assign({}, flow, { idle })); } catch (e) { return; }
          closeDrawer();
        }, 'primary'),
      ],
    });
  }

  async function startFlow(flow, loop, remember) {
    const id = flow.id;
    try {
      // 先保存默认设置再启动，避免 409/失步时 UI 上还是旧值
      if (remember) await saveFlow(Object.assign({}, flow, { loop }), true);
      const r = await api(`/api/flows/${id}/run`, {
        method: 'POST', body: { loop, idle: normalizeIdle(flow.idle) },
      });
      state.jobId = r.job.id;
      state.flowId = id;
      toast(loop.mode === 'once' ? '已开始执行' : `已开始执行 · ${loopLabel(loop)}`, 'ok');
      await loadJobs();
      render();
      dockReset(r.job.id);
      dockSetOpen(true);
      watchJob(r.job.id);
      return;
    } catch (e) {
      // 409 = 已经在跑（同编排/同账号）。不要报「启动失败」——那会让人
      // 以为没启动而反复点。直接把界面挂到正在跑的作业上，打开日志坞。
      if (/正在执行|执行中/.test(e.message || '')) {
        toast(e.message, 'warn');
        await attachRunningJob((j) => j.flow_id === id
          || (j.accounts || []).some((a) => flow.accounts.includes(a)));
        return;
      }
      toast('启动失败：' + e.message, 'err');
    }
  }

  let jobTimer = null;
  const trackedJobIds = new Set();
  function watchJobs() {
    if (jobTimer) return; // 一个轮询器，但跟踪全部运行中作业
    jobTimer = setInterval(async () => {
      try {
        const { jobs } = await api('/api/jobs');
        state.jobs = jobs || [];
        const running = state.jobs.filter((j) => j.status === 'running');
        running.forEach((job) => { applyJobStatus(job); dockFollow(job); });
        // 刚结束的作业再收一次尾，确保 RESULT 尾行进入日志
        state.jobs.filter((j) => j.status !== 'running' && trackedJobIds.has(j.id))
          .forEach((job) => dockFollow(job));
        trackedJobIds.clear();
        running.forEach((j) => trackedJobIds.add(j.id));
        if (!running.length) {
          clearInterval(jobTimer); jobTimer = null;
          await loadRuns();
          if (state.view === 'flows') render();
        } else if (runningSignature() !== state.flowsSignature) {
          state.flowsSignature = runningSignature();
          if (state.view === 'flows') render();
        }
      } catch (e) { clearInterval(jobTimer); jobTimer = null; }
    }, 1500);
  }
  function watchJob(jobId) { trackedJobIds.add(jobId); watchJobs(); }

  function applyJobStatus(job) {
    // 多编排并发时，只处理「当前显示这份编排」对应的作业，避免按 idx 串状态。
    const flow = currentFlow();
    if (state.view !== 'flows' || !flow || job.flow_id !== flow.id || job.status !== 'running') return;
    $$('.step').forEach((node) => {
      const id = node.dataset.step;
      const idx = flow.steps.findIndex((s) => s.id === id);
      if (idx < 0) return;
      // 清掉本步骤上全部旧标记：render 写入的 + 上一次轮询写入的
      $$('[data-status]', node).forEach((n) => n.remove());
      const st = job.steps[idx] && job.steps[idx].status;
      if (st && st !== 'pending') {
        const badge = statusBadge(st);
        badge.setAttribute('data-status', '1');
        node.querySelector('.step-line1').appendChild(badge);
      }
    });
  }

  /* ---------------- 运行日志坞 ----------------
     ① 所有账号/所有步骤的日志合并为一条时间线（按运行顺序交错追加）；
     ② 关键节点自动插入中文注释行（▸ 开头，主题色），便于快速扫读；
     ③ 面板顶部可拖拽调高度，偏好记忆；自动滚动且不打扰用户回看；
     ④ 收起后右下角留一个悬浮入口（运行中带状态点），随时点回。 */
  const DOCK_STORE_KEY = 'oas.dock.open';
  const DOCK_H_STORE_KEY = 'oas.dock.h';
  const DOCK_SCROLL_KEY = 'oas.dock.autoscroll';
  const dock = {
    jobIds: [], runs: [], lastStepRuns: '', nearBottom: true,
    lastNote: {}, selected: 'all', autoScroll: true, lastRound: 0,
  };

  // 关键节点 → 中文注释。只挑「扫一眼就该懂」的里程碑，避免刷屏。
  const PAGE_CN = {
    page_main: '庭院', page_town: '町中', page_exploration: '探索地图',
    page_rwt: '逢魔地图', page_battle: '战斗界面', page_shikigami_records: '式神录',
    page_demon_encounter: '逢魔入口', page_summon: '召唤', page_shop: '商店',
    page_friends: '好友', page_guild: '阴阳寮', page_town_pass: '探索入口',
    page_exp_entrance: '探索入口', page_exp_main: '探索地图', page_main_phb: '秘闻副本',
  };
  function dockAnnotate(line, run) {
    let m;
    if ((m = line.match(/^=== RUN (\S+) on config (\S+)/))) {
      const meta = taskMeta(m[1]) && state.catalog && state.catalog.tasks.find((t) => t.key.toLowerCase() === m[1].toLowerCase());
      const name = meta ? meta.name : m[1];
      return `开始执行：${name} · 账号 ${instName(m[2])}`;
    }
    if (/^=== RESULT: True/.test(line)) return '✓ 任务执行成功，收尾退出';
    if (/^=== RESULT: False/.test(line)) return '✗ 任务执行失败';
    if (/RESULT: True \(SystemExit/.test(line)) return '✓ 任务执行成功，收尾退出';
    if ((m = line.match(/Page arrived (\w+)/))) {
      const cn = PAGE_CN[m[1]] || m[1].replace(/^page_/, '');
      return `已进入「${cn}」`;
    }
    if ((m = line.match(/Detected random main costume: (\S+)/))) {
      const id = m[1].replace('costume_main', '').replace(/^_/, '');
      return `识别到庭院皮肤：${id ? '#' + id : '默认'}`;
    }
    if (/Boss battle already done/.test(line)) return '首领今日已挑战过，跳过首领战';
    if (/Lantern count success/.test(line)) return '灯笼已点满，开始处理奖励';
    if (/is empty$/.test(line) && /Lantern/.test(line)) return '灯笼已完成，跳过';
    if (/Battle Start/.test(line)) return '进入战斗';
    if (/Battle End/.test(line)) return '战斗结束';
    if (/Get reward success/.test(line)) return '奖励已领取';
    if (/Finding .* attempt/.test(line)) return '正在搜寻首领…';
    if (/Screenshot interval set/.test(line)) return '设备连接就绪，开始执行';
    if (/Image server ready|OCR server ready/.test(line)) return '识别服务就绪';
    if (/Stopping image server|Stopping OCR server/.test(line)) return null; // 常驻后不再出现，忽略
    if (/TaskEnd/.test(line)) return '任务正常结束';
    return null;
  }

  function dockSetOpen(open) {
    const node = $('#logDock');
    if (!node) return; // 页面结构不完整时静默降级，不能因此报「启动失败」
    node.hidden = !open;
    document.body.classList.toggle('dock-open', open);
    try { localStorage.setItem(DOCK_STORE_KEY, open ? '1' : '0'); } catch (e) { /* ignore */ }
    if (open) dockScrollAll();
    dockPeekUpdate();
  }

  function dockReset(jobIds) {
    const log = $('#dockLog');
    if (!log) return;
    dock.jobIds = Array.isArray(jobIds) ? jobIds.slice() : (jobIds ? [jobIds] : []);
    dock.runs = [];
    dock.lastStepRuns = '';
    dock.lastRound = 0;
    dock.nearBottom = true;
    dock.lastNote = {};
    dock.selected = 'all';
    log.innerHTML = '';
    dockRenderTabs();
    $('#logDock') && $('#logDock').classList.remove('failed');
    const dot = $('#dockDot'), sub = $('#dockSub');
    if (dot) dot.className = 'dot dot-ok';
    if (sub) sub.textContent = '正在启动引擎…';
  }

  function dockApplyFilter(node) {
    if (!node) return;
    // 没有实例归属的全局注释（轮次分隔等）在任何 Tab 下都保留
    node.hidden = !!(dock.selected !== 'all' && node.dataset.instance
      && node.dataset.instance !== dock.selected);
  }

  // 标题处的实例切换：全部 / 每个模拟器实例各一个 Tab
  function dockRenderTabs() {
    const box = $('#dockTabs');
    if (!box) return;
    const insts = [...new Set(dock.runs.map((r) => r.instance).filter(Boolean))];
    if (dock.selected !== 'all' && !insts.includes(dock.selected)) dock.selected = 'all';
    box.innerHTML = '';
    const mk = (key, label) => box.appendChild(el('button', {
      class: 'dock-tab' + (dock.selected === key ? ' active' : ''),
      text: label, type: 'button', 'data-act': 'dockInstance', 'data-id': key,
    }));
    mk('all', '全部');
    insts.forEach((i) => mk(i, instName(i)));
  }

  function dockSelectInstance(key) {
    dock.selected = key || 'all';
    $$('#dockLog > div').forEach(dockApplyFilter);
    dockRenderTabs();
    dockScrollAll();
  }

  function dockAppend(line, note, run) {
    const log = $('#dockLog');
    if (!log) return;
    const inst = (run && run.instance) || '';
    // 引擎常把同一事件打印两次；同一 run 内连续相同的注释只保留一条。
    const noteKey = (run && run.id) || 'all';
    if (note && dock.lastNote[noteKey] !== note) {
      const n = el('div', { class: 'ln-note', text: '▸ ' + note });
      n.dataset.instance = inst;
      log.appendChild(n);
      dockApplyFilter(n);
    }
    dock.lastNote[noteKey] = note;
    let cls = '';
    if (/ERROR|Traceback|failed|失败/i.test(line)) cls = 'ln-err';
    else if (/WARNING|warn/i.test(line)) cls = 'ln-warn';
    else if (/RESULT: True|SUCCESS/i.test(line)) cls = 'ln-ok';
    else if (/^===/.test(line)) cls = 'ln-head';
    const shown = inst ? `[${instName(inst)}] ${line}` : line;
    const node = el('div', { class: cls, text: shown });
    node.dataset.instance = inst;
    log.appendChild(node);
    dockApplyFilter(node);
    while (log.childNodes.length > 2400) log.removeChild(log.firstChild);
  }

  function dockScrollAll() {
    const box = $('#dockLog');
    if (!box || !dock.autoScroll || !dock.nearBottom) return;
    box.scrollTop = box.scrollHeight;
  }

  async function dockPull(run) {
    if (run.drained) return;
    try {
      const data = await api(`/api/runs/${run.id}?offset=${run.offset}`);
      const lines = data.lines || [];
      run.offset += lines.length;
      run.instance = data.instance || run.instance || '';
      run.label = `${instName(data.instance)} · ${taskMeta(data.task).name}`;
      run.status = data.status;
      run.result = data.result;
      run.lines = (run.lines || []).concat(lines);
      if (data.status !== 'running') run.drained = true;
      const log = $('#dockLog');
      if (log) dock.nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      lines.forEach((line) => dockAppend(line, dockAnnotate(line, run), run));
      dockRenderTabs();
      if (lines.length) dockScrollAll();
    } catch (e) { run.drained = true; }
  }

  // 收起后的悬浮入口：运行中才显示，点一下回来
  function dockPeekUpdate() {
    const peek = $('#dockPeek');
    if (!peek) return;
    const node = $('#logDock');
    const closed = !node || node.hidden;
    const running = dock.jobIds.length && dock.runs.some((r) => r.status === 'running');
    peek.hidden = !(closed && (running || dock.runs.length));
  }

  async function dockFollow(job) {
    if (!dock.jobIds.includes(job.id)) return;
    if (!$('#dockLog')) return;
    const idx = (typeof job.index === 'number' && job.index >= 0) ? job.index : null;
    const stepRuns = idx !== null ? ((job.steps[idx] && job.steps[idx].runs) || []) : [];
    const sig = stepRuns.join(',');
    if (sig && sig !== dock.lastStepRuns) {
      dock.lastStepRuns = sig;
      stepRuns.forEach((id) => {
        if (dock.runs.some((r) => r.id === id)) return;
        dock.runs.push({ id, label: '', offset: 0, status: 'running', drained: false });
      });
      // 一直循环时不要无限累积已读完的 run 句柄（日志行本身有 2400 行上限）
      if (dock.runs.length > 80) {
        const active = dock.runs.filter((r) => !r.drained);
        const drained = dock.runs.filter((r) => r.drained).slice(-40);
        dock.runs = active.concat(drained);
      }
    }
    if (job.round && job.round !== dock.lastRound) {
      dock.lastRound = job.round;
      const label = job.infinite ? `第 ${job.round} 轮 · 一直循环`
        : `第 ${job.round}/${job.total_rounds || 1} 轮`;
      dockAppend(`=== ${label} ===`, label, null);
    }
    await Promise.all(dock.runs.map(dockPull));

    // 头部：编排名 · 当前任务 · 进度
    const done = job.steps.filter((s) => ['ok', 'fail', 'skipped'].includes(s.status)).length;
    const cur = job.current ? taskMeta(job.current).name : null;
    let sub;
    if (job.status === 'running') {
      const prefix = loopRound(job) ? loopRound(job) + ' · ' : '';
      sub = job.note ? `${prefix}${job.note}`
        : cur ? `${prefix}正在执行：${cur} · 进度 ${done}/${job.steps.length} 步`
          : `${prefix}准备中…`;
    } else {
      sub = `已结束（${{ finished: '全部成功', failed: '有失败步骤', cancelled: '已停止' }[job.status] || job.status}）· ${done}/${job.steps.length} 步`;
    }
    const title = $('#dockTitle'), subEl = $('#dockSub'), dot = $('#dockDot'), dockEl = $('#logDock');
    if (title) title.textContent = job.flow_name;
    if (subEl) subEl.textContent = sub;
    if (dot) dot.className = 'dot ' + (job.status === 'running' ? 'dot-ok'
      : job.status === 'finished' ? 'dot-ok' : 'dot-err');
    dockPeekUpdate();
    if (!dockEl) return;
    if (job.status === 'failed' || job.status === 'cancelled') {
      dockEl.classList.add('failed');
    } else if (job.status === 'finished') {
      dockEl.classList.remove('failed');
      // 成功后 5 秒自动收起（用户手动重新打开不受影响）
      setTimeout(() => {
        if (dock.jobIds.includes(job.id) && !$('#logDock').hidden) dockSetOpen(false);
      }, 5000);
    }
  }

  // 拖拽调高：拖面板上边缘
  function dockInitResize() {
    const dockEl = $('#logDock'), handle = $('#dockResize');
    if (!dockEl || !handle) return;
    let startY = 0, startH = 0;
    const onMove = (e) => {
      const h = Math.min(Math.max(startY - e.clientY + startH, 120), Math.floor(window.innerHeight * 0.7));
      dockEl.style.height = h + 'px';
      document.body.style.setProperty('--dock-h', h + 'px');
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.classList.remove('dock-resizing');
      try { localStorage.setItem(DOCK_H_STORE_KEY, dockEl.style.height); } catch (e) { /* ignore */ }
    };
    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      startY = e.clientY;
      startH = dockEl.offsetHeight;
      document.body.classList.add('dock-resizing');
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  async function stopJob(jobId) {
    try {
      await api(`/api/jobs/${jobId}/stop`, { method: 'POST' });
      toast('已请求停止', 'warn');
      // 作业是异步收尾的，等一下再刷新，否则列表里还挂着「执行中」。
      setTimeout(async () => {
        try {
          await loadJobs();
          if (state.view === 'flows' || state.view === 'runs') render();
        } catch (e) { /* ignore */ }
      }, 1200);
    } catch (e) { toast(e.message, 'err'); }
  }

  /* ---- 步骤操作 ---- */
  async function mutateSteps(mutator) {
    const flow = currentFlow();
    if (!flow) return;
    flow.steps = mutator(flow.steps.slice());
    await saveFlow(flow, true);
  }

  async function stepUp(id) {
    await mutateSteps((steps) => {
      const i = steps.findIndex((s) => s.id === id);
      if (i > 0) steps.splice(i - 1, 0, steps.splice(i, 1)[0]);
      return steps;
    });
    render();
  }

  async function stepDown(id) {
    await mutateSteps((steps) => {
      const i = steps.findIndex((s) => s.id === id);
      if (i >= 0 && i < steps.length - 1) steps.splice(i + 1, 0, steps.splice(i, 1)[0]);
      return steps;
    });
    render();
  }

  async function stepDelete(id) {
    const flow = currentFlow();
    flow.steps = flow.steps.filter((s) => s.id !== id);
    await saveFlow(flow, true);
    render();
  }

  /* ---- 任务选择器 ---- */
  function openTaskPicker() {
    const flow = currentFlow();
    if (!flow) return toast('请先选择编排表', 'err');
    let cat = '全部';
    let q = '';

    const tabs = el('div', { class: 'chips' });
    const grid = el('div', { class: 'grid grid-3', style: 'margin-top:12px' });
    const teamCard = el('div', { class: 'task-card', style: 'margin-bottom:12px' },
      el('div', { class: 'tc-top' },
        el('span', { class: 'tc-name', text: '自定义组队' }),
        el('span', { class: 'badge badge-gold', text: '队伍配置' })),
      el('div', { class: 'tc-desc', text: '指定队长与队员，插在刷本任务之前；后面的组队玩法沿用这支队伍。' }),
      el('div', { class: 'tc-ops' }, btn('添加这一步', 'users', () => { closeModal(); openTeamDrawer(null); }, 'primary sm')),
    );
    const clickCard = el('div', { class: 'task-card', style: 'margin-bottom:12px' },
      el('div', { class: 'tc-top' },
        el('span', { class: 'tc-name', text: '自定义点击' }),
        el('span', { class: 'badge badge-gold', text: 'OCR / 找图 + 拟人点击' })),
      el('div', { class: 'tc-desc', text: '每层可选「直接识别并点击」（OCR 判定）或「滚动寻找并点击」（边滚边找图），命中后拟人点击。' }),
      el('div', { class: 'tc-ops' }, btn('选择 / 新建方案', 'plus', () => { closeModal(); openCustomClickLibrary(); }, 'primary sm')),
    );
    const cats = ['全部'].concat((state.catalog ? state.catalog.categories : []).map((c) => c.key));

    // 分类说明直接挂在标签下面：选哪个分类就说明这个分类在游戏里是什么。
    const catLine = el('p', { class: 'small muted mt-14' });
    function paintCatLine() {
      const info = (state.catalog ? state.catalog.categories : []).find((c) => c.key === cat);
      catLine.textContent = (info && info.cat) ? info.cat : '';
    }

    function paintTabs() {
      tabs.innerHTML = '';
      cats.forEach((c) => {
        const chip = el('button', { class: 'chip' + (cat === c ? ' active' : ''), text: c });
        chip.addEventListener('click', () => { cat = c; paintTabs(); paintCatLine(); paintGrid(); });
        tabs.appendChild(chip);
      });
    }

    function paintGrid() {
      grid.innerHTML = '';
      const tasks = state.catalog.tasks.filter((t) => {
        if (t.hidden) return false;
        if (t.pseudo) return false; // 伪任务（自定义组队）在弹窗顶部有专属卡片，不在网格里重复出现
        if (cat !== '全部' && t.category !== cat) return false;
        if (q && !(t.name.includes(q) || t.key.includes(q.toLowerCase()) || (t.desc || '').includes(q))) return false;
        return true;
      });
      if (!tasks.length) {
        grid.appendChild(el('div', { class: 'empty', style: 'grid-column:1/-1' }, el('strong', { text: '没有匹配的玩法' })));
        return;
      }
      tasks.forEach((t) => {
        const card = el('div', { class: 'task-card' },
          el('div', { class: 'tc-top' },
            el('span', { class: 'tc-name', text: t.name }),
            t.team ? el('span', { class: 'badge badge-gold', text: '可联动' }) : null,
            el('span', { class: 'badge badge-dim', text: t.category }),
          ),
          el('div', { class: 'tc-desc', text: t.desc || '' }),
          el('div', { class: 'tc-ops' },
            btn('配置并添加', 'plus', () => { closeModal(); openStepConfig(null, t.key); }, 'primary sm'),
          ),
        );
        grid.appendChild(card);
      });
    }

    const search = el('input', { class: 'input', placeholder: '搜索玩法名称…' });
    search.addEventListener('input', () => { q = search.value.trim(); paintGrid(); });

    paintTabs(); paintCatLine(); paintGrid();
    openModal({
      title: '添加任务',
      body: el('div', {}, teamCard, clickCard,
        el('div', { class: 'lib-toolbar' },
          el('div', { class: 'search' }, el('span', { html: icon('search', 14) }), search)),
        tabs, catLine, grid),
      foot: [btn('关闭', 'x', closeModal, 'ghost')],
    });
  }

  function applyTemplateSteps(tpl, flow) {
    const added = withTeamStep(tpl.steps.map((s) => ({
      task: s.task, mode: (s.mode === 'team' || s.mode === 'duo') ? 'team' : 'solo',
      patch: s.patch || {}, note: s.note || '', enabled: s.enabled !== false,
      plan_id: s.plan_id || null, plan_name: s.plan_name || '',
    })), flow.accounts);
    flow.steps = flow.steps.concat(added);
    return saveFlow(flow);
  }

  function openTemplatePicker() {
    const body = el('div');
    const mine = state.flowLib || [];
    if (!mine.length) {
      body.appendChild(el('div', { class: 'empty' },
        el('strong', { text: '还没有自定义方案' }),
        el('p', { text: '在编排详情点「存为自定义方案」即可保存。' })));
    } else {
      const list = el('div', { class: 'grid grid-2' });
      mine.forEach((tpl) => {
        list.appendChild(el('div', { class: 'task-card' },
          el('div', { class: 'tc-top' }, el('span', { class: 'tc-name', text: tpl.name })),
          el('div', { class: 'tc-desc', text: `${tpl.steps.length} 步` }),
          el('div', { class: 'tc-ops' },
            btn('追加步骤', 'plus', async () => {
              const flow = currentFlow();
              await applyTemplateSteps(tpl, flow);
              closeModal();
            }, 'sm primary'),
            btn('删除', 'trash', async () => {
              if (!confirm(`删除方案「${tpl.name}」？`)) return;
              await api(`/api/flow-library/${tpl.id}`, { method: 'DELETE' });
              await loadFlowLib();
              closeModal();
              toast('方案已删除', 'ok');
            }, 'sm ghost'),
          ),
        ));
      });
      body.appendChild(list);
    }
    openModal({ title: '选择方案', body, foot: [btn('关闭', 'x', closeModal, 'ghost')] });
  }

  /* ---- 步骤参数配置 ---- */
  async function openStepConfig(stepId, taskKey) {
    const flow = currentFlow();
    if (!flow) return;
    const isNew = !stepId;
    const step = isNew
      ? { id: 'tmp', task: taskKey, mode: 'solo', patch: {}, enabled: true, account: null }
      : JSON.parse(JSON.stringify(flow.steps.find((s) => s.id === stepId)));
    const meta = taskMeta(step.task);
    const acct = step.account || flow.accounts[0];
    const inst = instOf(acct);

    const body = el('div');
    const loading = el('div', { class: 'skel', style: 'height:120px' });
    body.appendChild(loading);

    // 模式选择
    const modeBox = el('div', { class: 'field' });
    let mode = step.mode;
    function paintMode() {
      modeBox.innerHTML = '';
      modeBox.appendChild(el('label', { text: '执行方式' }));
      const seg = el('div', { class: 'chips' });
      const solo = el('button', { class: 'chip' + (mode === 'solo' ? ' active' : ''), text: '单人执行' });
      solo.addEventListener('click', () => { mode = 'solo'; paintMode(); });
      seg.appendChild(solo);
      if (meta.team && flow.accounts.length > 1) {
        const teamBtn = el('button', {
          class: 'chip' + (mode === 'team' ? ' active' : ''),
          text: '组队执行（沿用队伍）',
        });
        teamBtn.addEventListener('click', () => { mode = 'team'; paintMode(); });
        seg.appendChild(teamBtn);
      }
      modeBox.appendChild(seg);
      if (mode === 'team') {
        const teamStep = flow.steps.filter((st) => st.task === 'team_setup').pop();
        const team = teamStep && teamStep.team;
        if (team && team.leader) {
          const members = (team.members || []).map(instName).join('、');
          modeBox.appendChild(el('p', {
            class: 'hint',
            text: `沿用「自定义组队」：队长 ${instName(team.leader)}${members ? ' · 队员 ' + members : ''}（执行时自动写入 user_status）`,
          }));
        } else {
          modeBox.appendChild(el('p', {
            class: 'hint',
            text: '还没有「自定义组队」步骤，将按编排表账号顺序执行（第一个为队长）。建议先插入一条自定义组队。',
          }));
        }
      } else {
        // 单人：选择由哪个账号执行。默认沿用步骤已有的账号，没有则用
        // 编排表第一个账号。绑定了多个模拟器时，每个账号都能跑单人任务。
        if (flow.accounts.length > 1) {
          const acctBox = el('div', { class: 'field', style: 'margin-top:10px' });
          acctBox.appendChild(el('label', { text: '执行账号' }));
          const chips = el('div', { class: 'chips' });
          flow.accounts.forEach((a) => {
            const chip = el('button', {
              class: 'chip' + (acct === a ? ' active' : ''),
              text: instName(a),
            });
            chip.addEventListener('click', () => {
              step.account = a;
              acctBox.querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
              chip.classList.add('active');
            });
            chips.appendChild(chip);
          });
          acctBox.appendChild(chips);
          modeBox.appendChild(acctBox);
        }
      }
      if (mode !== 'team' && !meta.team) {
        modeBox.appendChild(el('p', { class: 'hint', text: '该玩法引擎未提供组队状态字段，只能单人执行。' }));
      }
    }
    paintMode();
    body.appendChild(modeBox);

    const formBox = el('div');
    body.appendChild(formBox);

    let values = {};
    try {
      const [schema, current] = await Promise.all([
        api(`/api/tasks/${step.task}/schema`),
        inst ? api(`/api/instances/${inst.name}/tasks/${step.task}`).catch(() => null) : Promise.resolve(null),
      ]);
      loading.remove();
      if (schema.error) {
        formBox.appendChild(el('div', { class: 'empty' }, el('strong', { text: '无法读取表单' }), el('p', { text: schema.error })));
      } else {
        values = mergeValues(current ? current.config : {}, step.patch || {});
        renderForm(formBox, schema.sections, values);
      }
    } catch (e) {
      loading.remove();
      formBox.appendChild(el('div', { class: 'empty' }, el('strong', { text: '读取配置失败' }), el('p', { text: e.message })));
    }

    openDrawer({
      kicker: meta.category,
      title: meta.name,
      body: el('div', {}, el('p', { class: 'hint', style: 'margin-bottom:14px', text: meta.desc || '' }), body),
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn(isNew ? '加入编排' : '保存', 'check', async () => {
          const patch = {};
          Object.entries(values).forEach(([section, fields]) => {
            if (section === 'scheduler') return;
            if (fields && typeof fields === 'object' && !Array.isArray(fields)) patch[section] = fields;
          });
          if (isNew) {
            flow.steps.push({ task: step.task, mode, patch, enabled: true, account: step.account || null });
          } else {
            const target = flow.steps.find((s) => s.id === stepId);
            target.mode = mode;
            target.patch = patch;
            target.account = step.account || null;
          }
          await saveFlow(flow);
          closeDrawer();
        }, 'primary'),
      ],
    });
  }

  function mergeValues(base, patch) {
    const out = {};
    const sections = new Set(Object.keys(base || {}).concat(Object.keys(patch || {})));
    sections.forEach((s) => {
      const b = base && base[s] && typeof base[s] === 'object' ? base[s] : {};
      const p = patch && patch[s] && typeof patch[s] === 'object' ? patch[s] : {};
      out[s] = Object.assign({}, b, p);
    });
    return out;
  }

  function renderForm(root, sections, values) {
    sections.forEach((section, i) => {
      if (section.key === 'scheduler') return;
      const sec = el('div', { class: 'form-sec' + (i > 1 ? ' collapsed' : '') });
      const head = el('div', { class: 'form-sec-head' },
        el('h4', { text: section.label }),
        el('span', { class: 'chev', html: icon('down', 13) }),
      );
      head.addEventListener('click', () => sec.classList.toggle('collapsed'));
      const bodyEl = el('div', { class: 'form-sec-body' });
      const grid = el('div', { class: 'form-grid' });
      section.fields.forEach((f) => {
        if (f.type === 'object' || f.type === 'array') return;
        const cur = values[section.key] ? values[section.key][f.key] : undefined;
        const node = renderField(f, cur, (v) => {
          values[section.key] = values[section.key] || {};
          values[section.key][f.key] = v;
        });
        grid.appendChild(node);
      });
      bodyEl.appendChild(grid);
      sec.append(head, bodyEl);
      root.appendChild(sec);
    });
  }

  function renderField(f, value, onChange) {
    const wrap = el('div', { class: 'field' + (f.type === 'string' && (f.hint || '').length > 60 ? ' span-2' : '') });
    const mark = f.hint ? el('span', { class: 'qmark', text: '?', title: f.hint }) : null;
    const label = el('label', {}, f.label, mark);
    wrap.appendChild(label);

    if (f.enum) {
      const sel = el('select', { class: 'select' });
      f.enum.forEach((opt) => sel.appendChild(el('option', {
        value: opt,
        text: (f.enum_map && f.enum_map[String(opt)]) || opt,
        selected: String(value) === String(opt) ? '' : null,
      })));
      sel.addEventListener('change', () => onChange(sel.value));
      wrap.appendChild(sel);
    } else if (f.type === 'boolean') {
      const input = el('input', { type: 'checkbox', checked: !!value });
      input.addEventListener('change', () => onChange(input.checked));
      wrap.appendChild(el('label', { class: 'switch' }, input, el('span', { class: 'track' })));
    } else if (f.type === 'integer' || f.type === 'number') {
      const input = el('input', { class: 'input', type: 'number', value: value == null ? '' : value });
      if (f.min != null) input.min = f.min;
      if (f.max != null) input.max = f.max;
      input.addEventListener('input', () => onChange(input.value === '' ? null : Number(input.value)));
      wrap.appendChild(input);
    } else {
      const input = el('input', { class: 'input', value: value == null ? '' : value, placeholder: f.type === 'time' ? 'HH:MM:SS' : '' });
      input.addEventListener('input', () => onChange(input.value));
      wrap.appendChild(input);
    }
    if (f.hint) wrap.appendChild(el('div', { class: 'hint clamp', text: f.hint, title: f.hint }));
    return wrap;
  }

  /* ---------------- 任务库已移除 ----------------
     玩法信息在「添加任务」面板里直接给出，不需要单独一页。 */


  /* ---------------- 执行记录 ---------------- */
  function renderRuns(root) {
    const running = state.jobs.filter((j) => j.status === 'running');
    if (running.length) {
      root.appendChild(el('div', { class: 'panel', style: 'margin-bottom:16px' },
        el('div', { class: 'panel-head' }, el('h3', {}, '进行中 ', el('span', { class: 'badge badge-accent', text: String(running.length) }))),
        el('div', { class: 'panel-body', style: 'padding:0' },
          (() => {
            const table = el('table', { class: 'table' });
            table.innerHTML = '<thead><tr><th>编排表</th><th>当前步骤</th><th>进度</th><th>开始</th><th></th></tr></thead>';
            const tb = el('tbody');
            running.forEach((job) => {
              const done = job.steps.filter((s) => ['ok', 'fail'].includes(s.status)).length;
              tb.appendChild(el('tr', {},
                el('td', { text: job.flow_name }),
                el('td', { class: 'mono', text: job.current ? taskMeta(job.current).name : '—' }),
                el('td', { class: 'mono', text: `${loopRound(job) ? loopRound(job) + ' · ' : ''}${done}/${job.steps.length} 步` }),
                el('td', { class: 'mono muted', text: (job.started || '').replace('T', ' ') }),
                el('td', {}, el('button', { class: 'btn btn-sm btn-danger', text: '停止', 'data-act': 'stopJob', 'data-id': job.id })),
              ));
            });
            table.appendChild(tb);
            return table;
          })()),
      ));
    }

    root.appendChild(el('div', { class: 'section-title' }, el('h2', { text: '编排执行' })));
    if (!state.jobs.length) {
      root.appendChild(el('div', { class: 'empty' }, el('div', { html: icon('play', 26) }), el('strong', { text: '暂无编排执行记录' })));
    } else {
      const table = el('table', { class: 'table' });
      table.innerHTML = '<thead><tr><th>编排表</th><th>状态</th><th>进度</th><th>开始</th><th>耗时</th><th></th></tr></thead>';
      const tb = el('tbody');
      state.jobs.forEach((job) => {
        const done = job.steps.filter((s) => ['ok', 'fail', 'skipped'].includes(s.status)).length;
        tb.appendChild(el('tr', { class: 'row-click', 'data-act': 'openJob', 'data-id': job.id },
          el('td', {},
            el('div', { text: job.flow_name }),
            el('div', { class: 'small muted', text: loopLabel(job.loop)
              + (job.round ? ` · 已完成 ${job.round} 轮${job.infinite ? '（一直循环）' : ''}` : '') })),
          el('td', {}, statusBadge(job.status)),
          el('td', { class: 'mono', text: `${done}/${job.steps.length}` }),
          el('td', { class: 'mono muted', text: (job.started || '').replace('T', ' ') }),
          el('td', { class: 'mono muted', text: duration(job.started, job.finished) }),
          el('td', {}, el('span', { class: 'small muted', text: job.error || '' })),
        ));
      });
      table.appendChild(tb);
      root.appendChild(el('div', { class: 'panel' }, el('div', { class: 'panel-body', style: 'padding:0' }, table)));
    }

    root.appendChild(el('div', { class: 'section-title mt-20' }, el('h2', { text: '单次任务' })));
    if (!state.runs.length) {
      root.appendChild(el('div', { class: 'empty' }, el('strong', { text: '暂无单次任务记录' })));
    } else {
      const table = el('table', { class: 'table' });
      table.innerHTML = '<thead><tr><th>任务</th><th>账号</th><th>状态</th><th>开始</th><th>耗时</th><th></th></tr></thead>';
      const tb = el('tbody');
      state.runs.slice(0, 40).forEach((run) => {
        tb.appendChild(el('tr', {},
          el('td', { text: taskMeta(run.task).name }),
          el('td', { class: 'mono', text: run.instance }),
          el('td', {}, run.status === 'running' ? statusBadge('running') : (run.result ? statusBadge('ok') : statusBadge('fail'))),
          el('td', { class: 'mono muted', text: (run.started || '').replace('T', ' ') }),
          el('td', { class: 'mono muted', text: duration(run.started, run.finished) }),
          el('td', {}, el('button', { class: 'btn btn-sm btn-ghost', text: '日志', 'data-act': 'openLog', 'data-id': run.id, 'data-task': run.task })),
        ));
      });
      table.appendChild(tb);
      root.appendChild(el('div', { class: 'panel' }, el('div', { class: 'panel-body', style: 'padding:0' }, table)));
    }
  }

  function duration(start, end) {
    if (!start || !end) return '—';
    const ms = new Date(end) - new Date(start);
    if (!(ms >= 0)) return '—';
    const s = Math.round(ms / 1000);
    if (s < 60) return s + 's';
    const m = Math.floor(s / 60);
    return `${m}m${String(s % 60).padStart(2, '0')}s`;
  }

  function openJobDrawer(jobId) {
    const job = state.jobs.find((j) => j.id === jobId);
    if (!job) return;
    const body = el('div');
    let logs = null;
    const list = el('div', { class: 'steps' });
    job.steps.forEach((s, i) => {
      const meta = taskMeta(s.task);
      list.appendChild(el('div', { class: 'step' },
        el('div', { class: 'step-num' }, el('span', { text: String(i + 1).padStart(2, '0') })),
        el('div', { class: 'step-main' },
          el('div', { class: 'step-line1' }, el('span', { class: 'name', text: meta.name }),
            s.mode === 'team' ? el('span', { class: 'badge badge-gold', text: '组队' }) : null,
            statusBadge(s.status)),
          el('div', { class: 'step-line2' }, (s.runs || []).length
            ? s.runs.map((rid) => {
              const run = state.runs.find((r) => r.id === rid);
              return el('button', { class: 'btn btn-sm btn-ghost', text: '日志 ' + rid, 'data-act': 'openLog', 'data-id': rid });
            })
            : el('span', { text: '未执行' })),
        ),
        el('div', {}),
      ));
    });
    body.append(
      el('div', { class: 'row between', style: 'margin-bottom:12px' },
        el('div', {}, el('span', { class: 'small muted', text: '开始 ' + (job.started || '').replace('T', ' ') })),
        job.status === 'running' ? btn('停止', 'x', () => stopJob(job.id), 'danger') : statusBadge(job.status)),
      el('div', { class: 'small muted', style: 'margin-bottom:10px',
        text: `${loopLabel(job.loop)} · ${loopRound(job) || '共 1 轮'}${job.last_error ? ` · 上一轮失败：${job.last_error}` : ''}` }),
      el('div', { class: 'section-title' }, el('h2', { text: `${loopRound(job) || '第 1 轮'}步骤` })),
      list,
    );
    // 多轮作业时把每轮结果列出来，点「日志」能直接定位到那一轮的进程
    if ((job.rounds || []).length) {
      const rounds = el('div', { class: 'steps', style: 'margin-top:14px' });
      job.rounds.slice().reverse().forEach((r) => {
        rounds.appendChild(el('div', { class: 'step' },
          el('div', { class: 'step-num' }, el('span', { text: String(r.round).padStart(2, '0') })),
          el('div', { class: 'step-main' },
            el('div', { class: 'step-line1' },
              el('span', { class: 'name', text: `第 ${r.round} 轮` }),
              statusBadge(r.status === 'cancelled' ? 'cancelled' : (r.status === 'ok' ? 'ok' : 'fail'))),
            el('div', { class: 'step-line2' },
              el('span', { class: 'small muted', text: `${(r.started || '').replace('T', ' ')} → ${duration(r.started, r.finished)}` }),
              r.error ? el('span', { class: 'small', text: ' · ' + r.error }) : null,
              (r.runs || []).map((rid) => el('button', { class: 'btn btn-sm btn-ghost',
                text: '日志 ' + rid, 'data-act': 'openLog', 'data-id': rid })),
            ),
          ),
          el('div', {}),
        ));
      });
      body.append(el('div', { class: 'section-title mt-20' }, el('h2', { text: '轮次记录' })), rounds);
    }
    openDrawer({ kicker: '执行记录', title: job.flow_name, body, foot: [btn('关闭', 'x', closeDrawer, 'ghost')] });
  }

  function openLogDrawer(runId, taskName) {
    const body = el('div');
    const logBox = el('div', { class: 'log' });
    body.appendChild(logBox);
    openDrawer({ kicker: '实时日志', title: taskName || runId, body, foot: [btn('关闭', 'x', () => { if (window.__es) { window.__es.close(); window.__es = null; } closeDrawer(); }, 'ghost')] });

    if (window.__es) { window.__es.close(); window.__es = null; }
    const es = new EventSource(`/api/runs/${runId}/stream`);
    window.__es = es;
    let buffer = [];
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        (data.lines || []).forEach((line) => appendLine(logBox, line));
        if (data.status && data.status !== 'running') {
          es.close();
          window.__es = null;
        }
      } catch (e) { /* ignore */ }
    };
    es.onerror = () => { es.close(); window.__es = null; };
  }

  function appendLine(box, line) {
    let cls = '';
    if (/ERROR|Traceback|failed|失败/i.test(line)) cls = 'ln-err';
    else if (/WARNING|warn/i.test(line)) cls = 'ln-warn';
    else if (/RESULT: True|SUCCESS/i.test(line)) cls = 'ln-ok';
    else if (/^===/.test(line)) cls = 'ln-head';
    box.appendChild(el('div', { class: cls, text: line }));
    if (dock.autoScroll) box.scrollTop = box.scrollHeight;
  }

  /* ---------------- 已知问题 ---------------- */
  function renderIssues(root) {
    const issues = (state.catalog && state.catalog.issues) || [];
    const order = { error: 0, warn: 1, info: 2 };
    issues.slice().sort((a, b) => (order[a.severity] || 9) - (order[b.severity] || 9)).forEach((it) => {
      const card = el('div', { class: 'issue ' + it.severity },
        el('h4', {}, it.title,
          el('span', { class: 'badge ' + (it.severity === 'error' ? 'badge-err' : it.severity === 'warn' ? 'badge-warn' : 'badge-accent'),
            text: it.severity === 'error' ? '会导致失败' : it.severity === 'warn' ? '需要注意' : '说明' })),
        el('div', { class: 'scope', text: it.scope }),
        el('p', { text: it.detail }),
        el('div', { class: 'fix', text: '处理：' + it.fix }),
      );
      if (it.image) {
        card.appendChild(el('div', { class: 'issue-img' },
          el('img', { src: '/static/' + it.image, alt: it.title })));
      }
      root.appendChild(card);
    });
  }

  /* ---------------- 高级 ---------------- */
  function renderAdvanced(root) {
    root.appendChild(el('div', { class: 'section-title' }, el('h2', { text: '协助悬赏封印邀请' }),
      el('span', { class: 'sub', text: '好友发起协助邀请时的处理策略，按模拟器账号设置。' })));
    const popupPanel = el('div', { class: 'panel' });
    root.appendChild(popupPanel);
    paintPopupPolicy(popupPanel);
  }

  const POPUP_OPTIONS = [
    { value: 'reject', label: '关闭弹窗' },
    { value: 'accept', label: '接受' },
  ];

  /**
   * 悬赏封印协助邀请：好友随时可能发起，弹窗会盖住当前页面，
   * 让「准备」这类点击落到遮罩上。策略写在实例的 global_game.popup.wanted_assist。
   */
  async function paintPopupPolicy(panel) {
    panel.innerHTML = '';
    const body = el('div', { class: 'panel-body' });
    panel.appendChild(body);
    if (!state.instances.length) {
      body.appendChild(el('p', { class: 'small muted', text: '还没有实例。' }));
      return;
    }
    body.appendChild(el('p', { class: 'small muted', text: '读取实例配置…' }));
    const values = await Promise.all(state.instances.map(async (inst) => {
      try {
        const data = await api(`/api/instances/${inst.name}/raw`);
        const gg = (data.config && data.config.global_game) || {};
        return { inst, value: (gg.popup && gg.popup.wanted_assist) || 'reject' };
      } catch (e) {
        return { inst, value: 'reject' };
      }
    }));
    body.innerHTML = '';
    body.appendChild(el('div', { class: 'popup-row popup-head' },
      el('div', { class: 'popup-name', text: '模拟器账号' }),
      el('div', { class: 'popup-ops', text: '操作处理' })));
    values.forEach(({ inst, value }) => {
      const row = el('div', { class: 'popup-row' });
      row.appendChild(el('div', { class: 'popup-name' },
        el('strong', { text: inst.nickname || inst.name }),
        el('span', { class: 'badge badge-dim', text: inst.name })));
      const chips = el('div', { class: 'chips' });
      POPUP_OPTIONS.forEach((opt) => {
        const chip = el('button', { class: 'chip' + (value === opt.value ? ' active' : ''), text: opt.label });
        chip.addEventListener('click', async () => {
          try {
            await api(`/api/instances/${inst.name}/tasks/global_game`, {
              method: 'PUT', body: { config: { popup: { wanted_assist: opt.value } } },
            });
            toast(`已设为「${opt.label}」`, 'ok');
            paintPopupPolicy(panel);
          } catch (e) { toast('保存失败：' + e.message, 'err'); }
        });
        chips.appendChild(chip);
      });
      row.appendChild(chips);
      body.appendChild(row);
    });
  }

  /* ---------------- 抽屉 / 模态 ---------------- */
  function openDrawer({ kicker, title, body, foot }) {
    $('#drawerKicker').textContent = kicker || '';
    $('#drawerTitle').textContent = title || '';
    const bodyBox = $('#drawerBody');
    bodyBox.innerHTML = '';
    bodyBox.appendChild(body);
    const footBox = $('#drawerFoot');
    footBox.innerHTML = '';
    (foot || []).forEach((b) => footBox.appendChild(b));
    $('#drawer').hidden = false;
    $('#scrim').hidden = false;
    $('#drawer').setAttribute('aria-hidden', 'false');
  }

  function closeDrawer() {
    $('#drawer').hidden = true;
    $('#scrim').hidden = true;
    $('#drawer').setAttribute('aria-hidden', 'true');
    if (window.__es) { window.__es.close(); window.__es = null; }
  }

  function openModal({ title, body, foot }) {
    const card = $('#modalCard');
    card.innerHTML = '';
    card.appendChild(el('div', { class: 'modal-head' },
      el('h3', { text: title }),
      el('button', { class: 'icon-btn', 'data-act': 'closeModal', html: icon('x', 14) })));
    card.appendChild(el('div', { class: 'modal-body' }, body));
    const f = el('div', { class: 'modal-foot' });
    (foot || []).forEach((b) => f.appendChild(b));
    card.appendChild(f);
    $('#modal').hidden = false;
  }

  function closeModal() { $('#modal').hidden = true; }

  function field(label, control, hint) {
    return el('div', { class: 'field' },
      el('label', { text: label }),
      control,
      hint ? el('div', { class: 'hint', text: hint }) : null,
    );
  }

  /* ---------------- 事件分发 ---------------- */
  const ACTIONS = {
    go: (btn) => go(btn.dataset.view),
    reload: () => refreshAll().then(() => toast('已刷新', 'ok')),
    openIssues: () => go('issues'),
    closeDrawer,
    closeModal,
    bindDevice: (btn) => openBindDrawer(btn.dataset.serial),
    stepUp: (btn) => stepUp(btn.dataset.id),
    stepDown: (btn) => stepDown(btn.dataset.id),
    selectFlow: (btn) => selectFlow(btn.dataset.id),
    runFlow: (btn) => runFlow(state.flows.find((f) => f.id === btn.dataset.id)),
    newFlow: (btn) => openNewFlowDrawer(btn.dataset.account),
    stepDelete: (btn) => stepDelete(btn.dataset.id),
    stepConfig: (btn) => openStepConfig(btn.dataset.id),
    customClickConfig: (btn) => {
      const flow = currentFlow();
      const s = flow && flow.steps.find((x) => x.id === btn.dataset.id);
      if (!s) return;
      if (!s.plan_id || !state.customPlans.some((p) => p.id === s.plan_id)) {
        return openCustomClickLibrary({ forStep: s.id });
      }
      openCustomClickEditor(s.plan_id, false);
    },
    customClickSwap: (btn) => openCustomClickLibrary({ forStep: btn.dataset.id }),
    teamConfig: (btn) => openTeamDrawer(btn.dataset.id),
    openJob: (btn) => openJobDrawer(btn.dataset.id),
    openLog: (btn) => openLogDrawer(btn.dataset.id, taskMeta(btn.dataset.task).name),
    stopJob: (btn) => stopJob(btn.dataset.id),
    dockToggle: () => dockSetOpen($('#logDock') && $('#logDock').hidden),
    dockClear: () => {
      const log = $('#dockLog');
      if (log) log.innerHTML = '';
    },
    dockPeekOpen: () => dockSetOpen(true),
    dockInstance: (btn) => dockSelectInstance(btn.dataset.id),
  };

  document.addEventListener('click', (e) => {
    const node = e.target.closest('[data-act]');
    if (!node) return;
    const fn = ACTIONS[node.dataset.act];
    if (fn) { e.preventDefault(); fn(node, e); }
  });

  $('#scrim').addEventListener('click', closeDrawer);

  /* ---------------- 启动 ---------------- */
  async function boot() {
    if (window.oasDesktop && window.oasDesktop.isElectron) document.body.classList.add('electron');
    renderNav();
    dockInitResize();
    try {
      dock.autoScroll = localStorage.getItem(DOCK_SCROLL_KEY) !== '0';
      const cb = $('#dockAutoScroll');
      if (cb) {
        cb.checked = dock.autoScroll;
        cb.addEventListener('change', () => {
          dock.autoScroll = cb.checked;
          try { localStorage.setItem(DOCK_SCROLL_KEY, dock.autoScroll ? '1' : '0'); } catch (e) { /* ignore */ }
          if (dock.autoScroll) dockScrollAll();
        });
      }
    } catch (e) { /* ignore */ }
    // 恢复日志坞的显隐与高度偏好
    try {
      const savedH = localStorage.getItem(DOCK_H_STORE_KEY);
      if (savedH && $('#logDock')) {
        $('#logDock').style.height = savedH;
        document.body.style.setProperty('--dock-h', savedH);
      }
      if (localStorage.getItem(DOCK_STORE_KEY) === '1') dockSetOpen(true);
    } catch (e) { /* ignore */ }
    try {
      await refreshAll();
      setBridge(true);
      // 刷新页面时若有作业在跑，自动接上（日志坞继续显示，不打断观察）
      const running = (state.jobs || []).filter((j) => j.status === 'running');
      if (running.length && !dock.jobIds.length) {
        dockReset(running.map((j) => j.id));
        state.jobId = running[0].id;
        dockSetOpen(true);
        running.forEach((j) => watchJob(j.id));
      }
    } catch (e) {
      setBridge(false);
      toast('无法连接本地服务：' + e.message, 'err');
    }
    const query = new URLSearchParams(location.search);
    const wanted = query.get('flow');
    if (wanted && state.flows.some((f) => f.id === wanted)) state.flowId = wanted;
    const hash = (location.hash || '').replace('#', '');
    if (VIEW_TITLE[hash]) { state.view = hash; renderNav(); }
    render();
    setInterval(async () => {
      try {
        await Promise.all([loadJobs(), loadRuns()]);
        if (state.view === 'runs' || state.view === 'overview') render();
        // 编排页只在「有编排放手/收手」时重绘：执行中的进度靠 applyJobStatus
        // 局部刷新，整页重绘会把步骤上的进度标记一起刷掉。
        else if (state.view === 'flows' && runningSignature() !== state.flowsSignature) render();
      } catch (e) { /* ignore */ }
    }, 5000);
  }

  function setBridge(ok) {
    const box = $('#bridgeState');
    box.innerHTML = '';
    box.append(el('span', { class: 'dot ' + (ok ? 'dot-ok' : 'dot-err') }),
      el('span', { text: ok ? '引擎桥接已连接' : '桥接未连接' }));
  }

  window.addEventListener('hashchange', () => {
    const v = location.hash.replace('#', '');
    if (VIEW_TITLE[v] && v !== state.view) go(v);
  });

  boot();
})();
