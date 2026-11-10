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

  function btn(label, ico, onClick, kind) {
    const b = el('button', { class: 'btn' + (kind ? ' btn-' + kind : ''), html: icon(ico) + `<span>${esc(label)}</span>` });
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

  async function loadJobs() {
    const data = await api('/api/jobs');
    state.jobs = data.jobs || [];
  }

  async function loadRuns() {
    const data = await api('/api/runs');
    state.runs = data.runs || [];
  }

  async function refreshAll() {
    await Promise.all([loadCatalog(), loadInstances(), loadFlows(), loadJobs(), loadRuns()]);
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
    const device = state.devices.find((d) => d.serial === inst.serial) || null;
    const card = el('div', { class: 'acct' });
    const initial = (inst.nickname || inst.name).slice(0, 1).toUpperCase();
    card.appendChild(el('div', { class: 'acct-top' },
      el('div', { class: 'avatar' + (inst.primary ? '' : ' sub'), text: initial }),
      el('div', { class: 'acct-id' },
        el('strong', { text: inst.nickname || inst.name }),
        el('span', { text: inst.server ? `${inst.server} · ${inst.role_id || '未填ID'}` : '未填写区服' }),
      ),
      el('div', { class: 'grow' }),
      el('span', { class: 'step-status' },
        el('span', { class: 'dot ' + (inst.online ? 'dot-ok' : 'dot-err') }),
        el('span', { class: 'small muted', text: inst.online ? '在线' : '离线' }),
      ),
    ));

    // 正在做啥：运行中的单任务 run 是最直接的信号，能找到所属编排表就带上名字。
    const act = instActivity(inst);
    card.appendChild(el('div', { class: 'acct-act acct-act-' + act.tone },
      el('span', { class: 'badge ' + act.badge, text: act.label }),
      el('span', { class: 'small muted', text: act.detail }),
    ));

    card.appendChild(el('div', { class: 'acct-meta' },
      metaItem('模拟器', device
        ? `${inst.serial} · ${device.resolution || ''}`
        : `${inst.serial || '—'} · 未扫描到`),
      metaItem('点击/截图', `${inst.control_method || '?'} / ${inst.screenshot_method || '?'}`),
      metaItem('庭院皮肤', inst.costume_count ? `${inst.costume_count} 个候选` : '未配置（会失败）'),
      metaItem('编排表', (inst.flows && inst.flows.length) ? inst.flows.join('、') : '未加入'),
    ));
    card.appendChild(el('div', { class: 'acct-actions' },
      btn('测试连接', 'bolt', () => testInstance(inst.name), ''),
      btn('编辑资料', 'sliders', () => openProfileDrawer(inst), 'ghost'),
      btn('解绑', 'trash', () => removeInstance(inst.name), 'danger'),
    ));
    return card;
  }

  function instActivity(inst) {
    if (!inst.online) {
      return { tone: 'off', badge: 'badge-err', label: '离线', detail: '模拟器不在线' };
    }
    const run = state.runs.find((r) => r.instance === inst.name && r.status === 'running');
    if (!run) {
      return { tone: 'idle', badge: 'badge-dim', label: '暂无任务', detail: '' };
    }
    const flow = state.jobs.find((j) => j.id === run.batch);
    return {
      tone: 'run',
      badge: 'badge-accent',
      label: '正在执行',
      detail: taskMeta(run.task).name + (flow ? ` · ${flow.flow_name}` : ''),
    };
  }

  function metaItem(k, v) {
    return el('div', {}, el('span', { class: 'k', text: k }), el('span', { class: 'v', title: String(v), text: String(v) }));
  }

  /* ---------------- 账号绑定操作 ---------------- */

  async function testInstance(name) {
    toast('正在测试连接…');
    try {
      const r = await api(`/api/instances/${name}/test`, { method: 'POST' });
      if (r.online) toast(`连接正常 ${r.serial} · ${r.resolution || '分辨率未知'}`, 'ok');
      else toast('设备不在线，请检查模拟器与 adb 端口', 'err');
      await loadInstances();
      render();
    } catch (e) { toast('测试失败：' + e.message, 'err'); }
  }

  async function fillCostume(name) {
    try {
      await api(`/api/instances/${name}/costume/all`, { method: 'POST' });
      toast('已写入 19 个庭院皮肤候选', 'ok');
      await loadInstances();
      render();
    } catch (e) { toast('写入失败：' + e.message, 'err'); }
  }

  async function removeInstance(name) {
    if (!confirm(`确定解绑账号 ${name}？\n配置会被删除（.bak 备份保留）。`)) return;
    try {
      await api(`/api/instances/${name}`, { method: 'DELETE' });
      toast('已解绑', 'ok');
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
  const flowOwner = (flow) => ((flow.accounts && flow.accounts[0]) || '');
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
    const groups = new Map(state.instances.map((inst) => [inst.name, []]));
    state.flows.forEach((flow) => {
      const owner = flowOwner(flow);
      if (!groups.has(owner)) groups.set(owner, []);
      groups.get(owner).push(flow);
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
        el('strong', { class: 'grow', text: '未绑定账号' })));
      orphans.forEach((flow) => group.appendChild(flowItem(flow)));
      side.appendChild(group);
    }

    side.appendChild(el('button', { class: 'fl-new', 'data-act': 'newFlow' },
      el('span', { html: icon('plus', 13) }), el('span', { text: '新建编排' })));

    renderFlowDetail(detail);
    // 记住这一帧的「谁在跑」，轮询发现变化才重绘，避免每 5 秒把步骤进度刷掉。
    state.flowsSignature = runningSignature();
  }

  const runningSignature = () => state.jobs
    .filter((j) => j.status === 'running').map((j) => j.id).sort().join(',');

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
    if (running) meta.push('执行中');

    const item = el('div', {
      class: 'fl-item' + (state.flowId === flow.id ? ' active' : '') + (running ? ' running' : ''),
      'data-act': 'selectFlow', 'data-id': flow.id,
    }, el('div', { class: 'fl-item-main' },
      el('div', { class: 'fl-name', text: flow.name }),
      el('div', { class: 'fl-meta', text: meta.join(' · ') }),
    ));

    const act = el('button', {
      class: 'fl-run' + (running ? ' stop' : ''),
      title: running ? '停止执行' : (locked ? '该账号正在执行其它编排' : '执行这份编排'),
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
    ));
    head.appendChild(el('div', { class: 'row' },
      btn('改绑定', 'cog', () => openFlowBindDrawer(flow), 'ghost'),
      btn('重命名', 'sliders', () => renameFlow(flow), 'ghost'),
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
          el('span', { class: 'sub', text: `${done}/${job.steps.length} 步 · ${(job.started || '').replace('T', ' ')}` }),
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
      btn('从模板创建', 'copy', () => openTemplatePicker(), 'ghost'),
    );
    detail.appendChild(addBar);

    // 联动说明
    if (flow.accounts.length > 1) {
      detail.appendChild(el('div', { class: 'panel', style: 'margin-top:18px' },
        el('div', { class: 'panel-head' }, el('h3', { text: '组队联动说明' })),
        el('div', { class: 'panel-body' },
          el('p', { class: 'small muted', text: '联动分两步：先插入一条「自定义组队」指定队长与队员（队长不必是第一个账号），再把带「可联动」标记的玩法设为「组队执行」，它会沿用这支队伍。' }),
          el('p', { class: 'small muted mt-8', text: '执行时队长写入 user_status=leader，队员写入 member，所有进程并行启动；队长建房邀请，队员接受邀请。' }),
          el('p', { class: 'small muted mt-8', text: '前提：账号之间互为好友或同寮，队员端启动时停在庭院。当前已实测 2 人；3 人及以上沿用 1 队长 + N 队员机制，邀请时序尚未验证。' }),
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
      stepState ? statusBadge(stepState) : null,
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
      el('button', { class: 'icon-btn', title: '配置参数', 'data-act': 'stepConfig', 'data-id': step.id, html: icon('cog', 13) }),
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

  /* ---- 编排 CRUD ---- */
  function openNewFlowDrawer(account) {
    const nameInput = el('input', { class: 'input', placeholder: '如：日常一条龙 / 双开御魂' });
    const list = el('div', { class: 'tpl-list' });
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

    (state.catalog ? state.catalog.flow_templates : []).forEach((tpl) => {
      const card = el('div', { class: 'task-card' },
        el('div', { class: 'tc-top' }, el('span', { class: 'tc-name', text: tpl.name }),
          el('span', { class: 'badge ' + (tpl.accounts > 1 ? 'badge-gold' : 'badge-dim'), text: tpl.accounts > 1 ? '双账号联动' : '单账号' })),
        el('div', { class: 'tc-desc', text: tpl.desc }),
        el('div', { class: 'tc-ops' }, btn('用此模板', 'bolt', () => createFromTemplate(tpl, accounts, nameInput.value), 'sm')),
      );
      list.appendChild(card);
    });

    openDrawer({
      kicker: '任务编排',
      title: '新建编排表',
      body: el('div', {},
        field('编排表名称', nameInput),
        el('div', { class: 'field' }, el('label', { text: '绑定账号（第一个为队长；多开可绑定任意多个）' }), chips),
        el('p', { class: 'hint', text: '先建一张空表，再逐个添加任务；也可以直接套用下面的模板。绑定多个账号后，组队类玩法可设为联动步骤。' }),
        el('div', { class: 'section-title mt-14' }, el('h2', { text: '模板' })),
        list,
      ),
      foot: [
        btn('取消', 'x', closeDrawer, 'ghost'),
        btn('创建空表', 'plus', async () => {
          const name = nameInput.value.trim() || '未命名编排';
          if (!accounts.length) return toast('请先绑定账号', 'err');
          try {
            const r = await api('/api/flows', { method: 'POST', body: { name, accounts, steps: [] } });
            state.flowId = r.flow.id;
            await loadFlows();
            closeDrawer();
            go('flows');
            toast('编排已创建', 'ok');
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

  async function createFromTemplate(tpl, accounts, name) {
    if (!accounts.length) return toast('请先选择账号', 'err');
    const steps = withTeamStep(tpl.steps.map((s) => ({
      task: s.task, mode: s.mode === 'duo' ? 'team' : (s.mode || 'solo'),
      patch: s.patch || {}, enabled: true,
    })), accounts);
    try {
      const r = await api('/api/flows', {
        method: 'POST',
        body: { name: name.trim() || tpl.name, accounts, steps },
      });
      state.flowId = r.flow.id;
      await loadFlows();
      closeDrawer();
      go('flows');
      toast('已按模板创建', 'ok');
    } catch (e) { toast('创建失败：' + e.message, 'err'); }
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
      const r = await api(`/api/flows/${flow.id}`, { method: 'PUT', body: { name: flow.name, accounts: flow.accounts, steps: flow.steps } });
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

  async function runFlow(id) {
    if (!id) return toast('请先选择编排', 'err');
    const flow = state.flows.find((f) => f.id === id);
    if (flow && flowLocked(flow)) {
      toast('该账号正在执行其它编排', 'warn');
      await attachRunningJob((j) => j.flow_id === id
        || (flow && (j.accounts || []).some((a) => flow.accounts.includes(a))));
      return;
    }
    try {
      const r = await api(`/api/flows/${id}/run`, { method: 'POST' });
      state.jobId = r.job.id;
      state.flowId = id;
      toast('已开始执行', 'ok');
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
          || (flow && (j.accounts || []).some((a) => flow.accounts.includes(a))));
        return;
      }
      toast('启动失败：' + e.message, 'err');
    }
  }

  let jobTimer = null;
  function watchJob(jobId) {
    if (jobTimer) clearInterval(jobTimer);
    jobTimer = setInterval(async () => {
      try {
        const job = await api(`/api/jobs/${jobId}`);
        const idx = state.jobs.findIndex((j) => j.id === jobId);
        if (idx >= 0) state.jobs[idx] = job; else state.jobs.unshift(job);
        applyJobStatus(job);
        dockFollow(job);
        if (job.status !== 'running') {
          clearInterval(jobTimer); jobTimer = null;
          // 收尾再拉一次，确保 RESULT 尾行都进了面板
          dockFollow(job);
          await loadRuns();
          // 跑完就把执行条和步骤上的进度标记一起收掉。
          if (state.view === 'flows') render();
        }
      } catch (e) { clearInterval(jobTimer); jobTimer = null; }
    }, 1500);
  }

  function applyJobStatus(job) {
    // 只在运行中把进度刷到步骤上；结束后的状态不再展示，避免留下过期标记。
    if (state.view !== 'flows' || job.status !== 'running') return;
    $$('.step').forEach((node) => {
      const id = node.dataset.step;
      const idx = (currentFlow() || { steps: [] }).steps.findIndex((s) => s.id === id);
      if (idx < 0) return;
      const st = job.steps[idx] && job.steps[idx].status;
      const old = node.querySelector('[data-status]');
      if (old) old.remove();
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
  const dock = { jobId: null, runs: [], lastStepRuns: '', nearBottom: true, lastNote: null };

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

  function dockReset(jobId) {
    const log = $('#dockLog');
    if (!log) return;
    dock.jobId = jobId;
    dock.runs = [];
    dock.lastStepRuns = '';
    dock.nearBottom = true;
    dock.lastNote = null;
    log.innerHTML = '';
    $('#logDock') && $('#logDock').classList.remove('failed');
    const dot = $('#dockDot'), sub = $('#dockSub');
    if (dot) dot.className = 'dot dot-ok';
    if (sub) sub.textContent = '正在启动引擎…';
  }

  function dockAppend(line, note) {
    const log = $('#dockLog');
    if (!log) return;
    // 引擎常把同一事件打印两次（如 Page arrived 成对出现）：
    // 连续相同的注释只保留一条，原始行照常保留。
    if (note && note !== dock.lastNote) {
      log.appendChild(el('div', { class: 'ln-note', text: '▸ ' + note }));
    }
    dock.lastNote = note;
    let cls = '';
    if (/ERROR|Traceback|failed|失败/i.test(line)) cls = 'ln-err';
    else if (/WARNING|warn/i.test(line)) cls = 'ln-warn';
    else if (/RESULT: True|SUCCESS/i.test(line)) cls = 'ln-ok';
    else if (/^===/.test(line)) cls = 'ln-head';
    log.appendChild(el('div', { class: cls, text: line }));
    // 防爆内存：整场编排最多留 1600 行（含注释行）
    while (log.childNodes.length > 1600) log.removeChild(log.firstChild);
  }

  function dockScrollAll() {
    const box = $('#dockLog');
    if (!box || !dock.nearBottom) return;
    box.scrollTop = box.scrollHeight;
  }

  async function dockPull(run) {
    if (run.drained) return;
    try {
      const data = await api(`/api/runs/${run.id}?offset=${run.offset}`);
      const lines = data.lines || [];
      run.offset += lines.length;
      run.label = `${instName(data.instance)} · ${taskMeta(data.task).name}`;
      run.status = data.status;
      run.result = data.result;
      if (data.status !== 'running') run.drained = true;
      const log = $('#dockLog');
      if (log) dock.nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      lines.forEach((line) => dockAppend(line, dockAnnotate(line, run)));
      if (lines.length) dockScrollAll();
    } catch (e) { run.drained = true; }
  }

  // 收起后的悬浮入口：运行中才显示，点一下回来
  function dockPeekUpdate() {
    const peek = $('#dockPeek');
    if (!peek) return;
    const node = $('#logDock');
    const closed = !node || node.hidden;
    const running = dock.jobId && dock.runs.some((r) => r.status === 'running');
    peek.hidden = !(closed && (running || dock.runs.length));
  }

  async function dockFollow(job) {
    if (dock.jobId !== job.id) return;
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
    }
    await Promise.all(dock.runs.map(dockPull));

    // 头部：编排名 · 当前任务 · 进度
    const done = job.steps.filter((s) => ['ok', 'fail', 'skipped'].includes(s.status)).length;
    const cur = job.current ? taskMeta(job.current).name : null;
    let sub;
    if (job.status === 'running') {
      sub = cur ? `正在执行：${cur} · 进度 ${done}/${job.steps.length} 步` : `准备中…`;
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
        if (dock.jobId === job.id && !$('#logDock').hidden) dockSetOpen(false);
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
        el('span', { class: 'badge badge-gold', text: '队伍配置' }),
        el('span', { class: 'badge badge-dim', text: '非游戏玩法' })),
      el('div', { class: 'tc-desc', text: '指定队长与队员，插在刷本任务之前；后面的组队玩法沿用这支队伍。' }),
      el('div', { class: 'tc-ops' }, btn('添加这一步', 'users', () => { closeModal(); openTeamDrawer(null); }, 'primary sm')),
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
      body: el('div', {}, teamCard,
        el('div', { class: 'lib-toolbar' },
          el('div', { class: 'search' }, el('span', { html: icon('search', 14) }), search)),
        tabs, catLine, grid),
      foot: [btn('关闭', 'x', closeModal, 'ghost')],
    });
  }

  function openTemplatePicker() {
    const list = el('div', { class: 'grid grid-2' });
    (state.catalog ? state.catalog.flow_templates : []).forEach((tpl) => {
      list.appendChild(el('div', { class: 'task-card' },
        el('div', { class: 'tc-top' }, el('span', { class: 'tc-name', text: tpl.name })),
        el('div', { class: 'tc-desc', text: tpl.desc }),
        el('div', { class: 'tc-ops' },
          btn('追加步骤', 'plus', async () => {
            const flow = currentFlow();
            const added = withTeamStep(tpl.steps.map((s) => ({
              task: s.task, mode: s.mode === 'duo' ? 'team' : (s.mode || 'solo'),
              patch: s.patch || {}, enabled: true,
            })), flow.accounts);
            flow.steps = flow.steps.concat(added);
            await saveFlow(flow);
            closeModal();
          }, 'sm primary')),
      ));
    });
    openModal({ title: '模板步骤', body: list, foot: [btn('关闭', 'x', closeModal, 'ghost')] });
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
                el('td', { class: 'mono', text: `${done}/${job.steps.length}` }),
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
          el('td', { text: job.flow_name }),
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
      list,
    );
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
    box.scrollTop = box.scrollHeight;
  }

  /* ---------------- 已知问题 ---------------- */
  function renderIssues(root) {
    const issues = (state.catalog && state.catalog.issues) || [];
    const order = { error: 0, warn: 1, info: 2 };
    issues.slice().sort((a, b) => (order[a.severity] || 9) - (order[b.severity] || 9)).forEach((it) => {
      root.appendChild(el('div', { class: 'issue ' + it.severity },
        el('h4', {}, it.title,
          el('span', { class: 'badge ' + (it.severity === 'error' ? 'badge-err' : it.severity === 'warn' ? 'badge-warn' : 'badge-accent'),
            text: it.severity === 'error' ? '会导致失败' : it.severity === 'warn' ? '需要注意' : '说明' })),
        el('div', { class: 'scope', text: it.scope }),
        el('p', { text: it.detail }),
        el('div', { class: 'fix', text: '处理：' + it.fix }),
      ));
    });
  }

  /* ---------------- 高级 ---------------- */
  function renderAdvanced(root) {
    root.appendChild(el('div', { class: 'section-title' }, el('h2', { text: '实例原始配置' }),
      el('span', { class: 'sub', text: '直接编辑引擎 JSON，危险操作请先备份。' })));
    const grid = el('div', { class: 'grid grid-2' });
    state.instances.forEach((inst) => {
      grid.appendChild(el('div', { class: 'task-card' },
        el('div', { class: 'tc-top' }, el('span', { class: 'tc-name', text: inst.nickname || inst.name }),
          el('span', { class: 'badge badge-dim', text: inst.name })),
        el('div', { class: 'tc-desc', text: `设备 ${inst.serial} · 皮肤候选 ${inst.costume_count}` }),
        el('div', { class: 'tc-ops' },
          btn('打开 JSON', 'cog', () => openRawDrawer(inst.name), 'sm'),
          btn('全选皮肤', 'check', () => fillCostume(inst.name), 'sm ghost')),
      ));
    });
    root.appendChild(grid);

    root.appendChild(el('div', { class: 'section-title mt-20' }, el('h2', { text: '弹窗处理' })));
    const popupPanel = el('div', { class: 'panel' });
    root.appendChild(popupPanel);
    paintPopupPolicy(popupPanel);

    root.appendChild(el('div', { class: 'section-title mt-20' }, el('h2', { text: '联动总线（可选）' })));
    root.appendChild(el('div', { class: 'panel' }, el('div', { class: 'panel-body' },
      el('p', { class: 'small muted', text: '引擎自带基于 MQTT 的跨进程联动总线（global_game.team_flow）。本工具默认使用「双进程并行 + 角色注入」，不依赖 broker；只有在你有私有 MQTT 服务时才需要开启它。' }),
      el('p', { class: 'small muted mt-8', text: '配置项：broker / port / transport / ca / username / password，位于各实例 JSON 的 global_game.team_flow。' }),
    )));
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
    values.forEach(({ inst, value }) => {
      const row = el('div', { class: 'popup-row' });
      row.appendChild(el('div', { class: 'popup-name' },
        el('strong', { text: inst.nickname || inst.name }),
        el('span', { class: 'badge badge-dim', text: inst.name }),
        el('span', { class: 'popup-label', text: '协助悬赏封印邀请' })));
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

  async function openRawDrawer(name) {
    const data = await api(`/api/instances/${name}/raw`);
    const area = el('textarea', { class: 'textarea', style: 'height:520px' });
    area.value = JSON.stringify(data.config, null, 2);
    openDrawer({
      kicker: '高级', title: name + '.json', body: area,
      foot: [btn('关闭', 'x', closeDrawer, 'ghost'),
        btn('保存', 'check', async () => {
          try {
            const parsed = JSON.parse(area.value);
            await api(`/api/instances/${name}/raw`, { method: 'PUT', body: { config: parsed } });
            toast('已保存', 'ok');
            closeDrawer();
            await loadInstances();
            render();
          } catch (e) { toast('保存失败：' + e.message, 'err'); }
        }, 'primary')],
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
    runFlow: (btn) => runFlow(btn.dataset.id),
    newFlow: (btn) => openNewFlowDrawer(btn.dataset.account),
    stepDelete: (btn) => stepDelete(btn.dataset.id),
    stepConfig: (btn) => openStepConfig(btn.dataset.id),
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
      const running = (state.jobs || []).find((j) => j.status === 'running');
      if (running && !dock.jobId) {
        dockReset(running.id);
        state.jobId = running.id;
        dockSetOpen(true);
        watchJob(running.id);
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
