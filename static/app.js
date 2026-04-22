/**
 * 松江快聘 GEO Pipeline v2.0 - 操作流驱动前端
 *
 * 核心设计: 用户进来就知道下一步做什么
 * 流程: 上传数据(1) → 执行流水线(2) → 查看结果(3) → 监控效果(4)
 */

// ==================== 全局状态 ====================
const State = {
    page: 'workflow',
    selectedFile: null,
    isRunning: false,
    theme: localStorage.getItem('geo-theme') || 'light'
};

// ==================== API 客户端 ====================
const API = {
    async get(path) { return this._req('GET', path); },
    async post(path, body) { return this._req('POST', path, body); },
    async put(path, body) { return this._req('PUT', path, body); },

    async _req(method, path, body) {
        try {
            const opts = { method, headers: { 'Content-Type': 'application/json' } };
            if (body) opts.body = JSON.stringify(body);
            const r = await fetch(path, opts);
            const ct = r.headers.get('content-type');
            const data = ct?.includes('json') ? await r.json() : await r.text();
            return { ok: r.ok, status: r.status, data };
        } catch (e) {
            console.error('[API]', e); return { ok: false, error: e.message };
        }
    },
    
    // 文件上传用原生fetch (multipart)
    uploadCSV(formData) { return fetch('/api/pipeline/upload', { method:'POST', body: formData }); }
};

// ==================== Toast ====================
function toast(msg, type='info') {
    const c = document.getElementById('toastStack');
    const icons={success:'✅',error:'❌',warning:'⚠️',info:'ℹ️'};
    const el=document.createElement('div');
    el.className=`toast ${type}`;
    // [X-05] 安全: msg 通过 textContent 注入，防止XSS
    const iconSpan = document.createElement('span');
    iconSpan.textContent = icons[type] || '';
    const msgSpan = document.createElement('span');
    msgSpan.textContent = msg;
    el.appendChild(iconSpan);
    el.appendChild(msgSpan);
    c.appendChild(el);
    setTimeout(()=>{el.style.opacity='0';setTimeout(()=>el.remove(),300)},3500);
}

// ==================== 导航切换 ====================
function switchPage(name) {
    State.page = name;
    document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
    document.querySelectorAll('.nav-icon-btn').forEach(b=>b.classList.remove('active'));
    const pg = document.getElementById(`page-${name}`);
    if(pg) pg.classList.add('active');
    document.querySelector(`[data-page="${name}"]`)?.classList.add('active');

    // 页面加载钩子
    if(name==='workflow') Workflow.loadStats();
    if(name==='jobs') Jobs.load(1);
    if(name==='monitor') Monitor.load();
    if(name==='config') Config.load();
    if(name==='geo-framework') GEOFramework.load();
    if(name==='geo-audit') { GEOAudit.init(); GEOAudit.run(); }
    if(name==='keywords') Keywords.load();
}

function toggleTheme() {
    State.theme = State.theme === 'light' ? 'dark' : 'light';
    document.body.dataset.theme = State.theme;
    const btn = document.querySelector('.icon-nav .nav-icon-btn:last-child');
    if(btn) btn.innerHTML = State.theme === 'dark' ? '☀️' : '🌙';
    localStorage.setItem('geo-theme', State.theme);
}
function refreshData() {
    if(State.page==='workflow') Workflow.loadStats();
    if(State.page==='jobs') Jobs.load(1);
    if(State.page==='monitor') Monitor.load();
    if(State.page==='config') Config.load();
    toast('数据已刷新','success');
}


// ============================================================
//  PAGE 1: WORKFLOW — 核心操作流程
// ============================================================
var Workflow = window.Workflow = {

    /** 初始化上传绑定 */
    initUpload() {
        const zone = document.getElementById('uploadZone');
        const input = document.getElementById('fileInput');
        if(!zone||!input) return;

        zone.onclick = () => input.click();
        zone.ondragover = e => { e.preventDefault(); zone.classList.add('dragover'); };
        zone.ondragleave = () => zone.classList.remove('dragover');
        zone.ondrop = e => {
            e.preventDefault(); zone.classList.remove('dragover');
            if(e.dataTransfer.files.length) this.handleFile(e.dataTransfer.files[0]);
        };
        input.onchange = e => { if(e.target.files.length) this.handleFile(e.target.files[0]); };

        // 模式联动
        document.getElementById('pipelineMode').onchange = e => {
            const isDb = e.target.value === 'db';
            toggleEl('fileInfoBar', false);
            toggleEl('dbModeOpts', isDb);
            toggleEl('uploadZone', !isDb);
        };
        
        // 移除文件
        document.getElementById('removeFileBtn').onclick = () => {
            State.selectedFile = null;
            toggleEl('fileInfoBar', false);
            document.getElementById('fileInput').value = '';
        };
    },

    /** 处理文件上传 */
    async handleFile(file) {
        if(!file.name.endsWith('.csv')){toast('请选择 .csv 格式文件','error');return;}
        this.log(`正在上传: ${file.name} ...`,'info');

        const fd = new FormData();
        fd.append('file', file);

        try{
            const r = await API.uploadCSV(fd);
            const d = await r.json();
            
            if(r.ok && d.success){
                State.selectedFile = d.path;
                // 显示文件信息栏
                document.getElementById('fileNameDisplay').textContent = d.filename;
                document.getElementById('fileMetaDisplay').textContent = `${d.size_human} · 预览${d.preview_count}条`;
                toggleEl('fileInfoBar', true);
                
                // [W1] 渲染 CSV 预览表格
                this._renderCsvPreview(d);

                this.log(`✅ 上传成功: ${d.size_human}, 解析到 ${d.preview_count} 条记录`,'ok');
                toast('文件上传成功!','success');

                // 更新步骤条状态
                this.setWfStep(1, 'done');
                this.setWfStep(2, 'active'); // 引导用户下一步
                
            } else {
                this.log(`❌ 上传失败: ${d.error}`,'error');
                toast(d.error||'上传失败','error');
            }
        }catch(e){this.log(`上传异常: ${e.message}`,'error');}
    },

    /** 执行流水线 */
    async execute(){
        if(State.isRunning) return;

        try {
            const mode = document.getElementById('pipelineMode').value;
            const body = { mode };

            if(mode !== 'db' && !State.selectedFile){
                toast('请先上传 CSV 文件','warning'); return;
            }
            if(mode !== 'db') body.csv_file = State.selectedFile;
            if(mode === 'db'){
                body.limit = +document.getElementById('dbLimit')?.value||50;
                body.category = document.getElementById('dbCategory')?.value||null;
                body.urgent_only = document.getElementById('urgentOnly')?.checked||false;
            }

            // UI状态变更
            State.isRunning = true;
            const btn = document.getElementById('runPipelineBtn');
            btn.disabled = true; btn.textContent = '⏳ 执行中...';

        // 展开进度面板
        toggleEl('progressCard', true);
        this.initPhaseProgress();

        // [H-03] 改为基于阶段的真实进度模拟（非线性缓动，前慢后快）
        const phases = [
            {name:'合规闸门', weight:15},
            {name:'意图路由', weight:20},
            {name:'内容工厂', weight:30},
            {name:'API推送',  weight:25},
            {name:'监控记录', weight:10}
        ];
        let currentPhase = 0;
        let phasePct = 0;
        let totalPct = 0;

        this._progressTimer = setInterval(()=>{
            // 每个阶段内部使用 easeOut 缓动（开始快，后期减速接近完成态）
            const speed = Math.max(1, (100 - phasePct) / 40);
            phasePct += speed * (2 + Math.random());
            if(phasePct >= 100){
                phasePct = 0;
                currentPhase++;
                if(currentPhase < phases.length){
                    this.setWfPhase(currentPhase, 'done');
                }
            }
            if(currentPhase < phases.length){
                totalPct = phases.slice(0,currentPhase).reduce((s,p)=>s+p.weight,0)
                        + (phases[currentPhase].weight * phasePct/100);
                this.setWfPhase(currentPhase, 'running');
            } else {
                totalPct = Math.min(totalPct + 0.5, 95); // 上限95%，等后端真实结果
            }
            document.getElementById('overallProgress').style.width = `${totalPct}%`;
            document.getElementById('progressBadge').textContent =
                currentPhase < phases.length ? `${phases[currentPhase].name}...` : '等待结果';
        },600);

        this.log('═════════ 启动 GEO 流水线 ═════════','phase');
        this.log(`模式: ${mode.toUpperCase()} | 时间: ${new Date().toLocaleTimeString()}`,'info');

        this.setWfStep(2, 'running');

        const r = await API.post('/api/pipeline/run', body);
        clearInterval(this._progressTimer);

        if(r.status === 202){
            this.log('✅ 任务已提交, 等待后台处理...','ok');
            this.pollResult(r.data.task_id);
        } else {
            this.log(`❌ 提交失败: ${r.data?.error}`,'error');
            this.finish(false);
        }

        } catch(e) {
            clearInterval(this._progressTimer||'');
            this.log(`执行异常: ${e.message}`,'error');
            toast('流水线执行异常: '+e.message,'error');
            this.finish(false);
        }
    },

    /** 轮询执行结果 */
    pollResult(tid){
        let attempts=0;
        const iv=setInterval(async()=>{
            attempts++;
            const hr = await API.get('/api/history');
            const last = hr.data?.history?.find(h=>h.id===tid);

            if(last && last.result){
                clearInterval(iv);
                this.showResult(last.result, last.mode);
            } else if(attempts > 30){
                clearInterval(iv);
                this.log('⚠️ 等待超时, 请刷新页面查看','warn');
                this.finish(false);
            } else {
                // 更新阶段UI模拟
                this.updatePhaseSim(attempts);
                document.getElementById('overallProgress').style.width = `${Math.min(attempts*3,88)}%`;
            }
        },1500);
    },

    /** 显示最终结果 */
    showResult(result){
        document.getElementById('overallProgress').style.width = '100%';
        document.getElementById('progressBadge').textContent = '完成 ✓';

        const ok = result.status === 'success'||result.status === 'dry_run'||result.status === 'empty';

        // 更新所有阶段为完成状态
        this.setAllPhasesDone(ok);

        this.log(`${ok?'═══ 执行完成 ═══':'═══ 执行失败 ═══'}`, ok?'ok':'error');
        this.log(`耗时: ${result.duration || '?'} 秒`,'info');

        if(ok){
            const phases = result.phase_results || {};
            const names = {
                compliance_gate: '合规闸门', intent_routing: '意图路由',
                content_factory: '内容工厂', api_signaler: 'API推送', monitoring: '监控记录'
            };
            Object.entries(phases).forEach(([k,v])=>{
                this.log(`  ✅ ${names[k]||k}: ${JSON.stringify(v).substring(0,80)}`,'ok');
            });
            toast('🎉 流水线执行成功!','success');

            this.setWfStep(2, 'done');
            this.setWfStep(3, 'active'); // 引导查看结果

        } else {
            this.log(`  ❌ 错误: ${esc(result.error_message)||'未知错误'}`,'error');
            toast(esc(result.error_message)||'执行失败','error');
        }

        // 结果摘要卡片 [安全] 使用 textContent 防止 XSS
        const summary = document.getElementById('resultSummary');
        toggleEl('resultSummary', true);
        const pre = document.createElement('pre');
        pre.style.cssText = 'background:var(--gray-50);padding:16px;border-radius:8px;font-size:12px;text-align:left;white-space:pre-wrap;overflow:auto;max-height:280px;';
        pre.textContent = JSON.stringify(result, null, 2);

        summary.innerHTML = `
            <div style="text-align:center;padding:20px;">
                <div style="font-size:48px;margin-bottom:12px;">${ok?'🎉':'❌'}</div>
                <h3 style="margin-bottom:8px">${ok?'GEO 流水线执行成功':'执行失败'}</h3>
            </div>`;
        summary.querySelector('div').appendChild(pre);

        this.finish(ok);
    },

    finish(ok){
        State.isRunning = false;
        const btn = document.getElementById('runPipelineBtn');
        btn.disabled = false;
        btn.textContent = ok? '▶ 再次执行' : '▶ 重新执行';
        
        if(!ok)this.setWfStep(2, 'active');
        
        // 刷新统计数据
        setTimeout(()=>Workflow.loadStats(),1000);
    },

    /** 测试数据库连接 */
    async testDb(){
        this.log('测试数据库连接...','info');
        const r = await API.get('/api/status');
        if(r.data?.database?.connected){
            this.log(`✅ 数据库已连接: ${r.data.database.database} (${r.data.database.version})`,'ok');
            toast('数据库连接正常!','success');
        } else {
            this.log(`❌ 未连接: ${r.data?.database?.available?'检查配置':'SQLite不可用'}`,'error');
        }
    },

    // ---- 日志输出 ----
    log(msg, type='info'){
        const el = document.getElementById('logConsole');
        if(!el) return;
        const line = document.createElement('div');
        line.className = `log-${type}`;
        line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
        el.appendChild(line);
        el.scrollTop = el.scrollHeight;
    },

    // ---- 步骤条控制 ----
    setWfStep(n, state){
        const step = document.querySelector(`.wfs-step[data-wf="${n}"]`);
        if(!step) return;
        step.classList.remove('active','completed');
        if(state==='active') step.classList.add('active');
        if(state==='done') step.classList.add('completed');
        if(state==='running'){
            step.classList.add('active');
            step.querySelector('.wfs-num').innerHTML = `<span style="animation:spin-dot 1s infinite;display:inline-block;">⏳</span>`;
        }
    },

    // ---- 统计卡片 ----
    async loadStats(){
        const [sr, str] = await Promise.all([API.get('/api/status'), API.get('/api/stats')]);

        // DB状态
        const badge = document.getElementById('dbStatus');
        if(sr.data?.database?.connected){
            badge.className='status-pill online'; badge.innerHTML='<span class="status-dot"></span> DB 已连接';
        }else{
            badge.className='status-pill offline'; badge.innerHTML='<span class="status-dot"></span> 未连接';
        }

        // 快速统计
        const s = str.data||{};
        const exec = s.execution||{};
        const items = [
            { icon:'📋', label:'活跃岗位', value:s.total_active||0, color:'#2563eb' },
            { icon:'✅', label:'合规通过率', value:`${exec.success_rate||0}%`, color:'#059669' },
            { icon:'🔥', label:'急招岗位', value:s.urgent_count||0, color:'#d97706' },
            { icon:'▶️', label:'总执行次数', value:exec.total_executions||0, color:'#dc2626' },
            { icon:'⏱️', label:'平均耗时', value:`${exec.avg_duration||0}s`, color:'#7c3aed' },
        ];

        document.getElementById('quickStats').innerHTML = items.map(it=>`
            <div class="phase-card">
                <div class="phase-icon">${it.icon}</div>
                <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:10px;">
                    <div>
                        <div style="font-size:26px;font-weight:700;color:${it.color}">${it.value}</div>
                        <div style="font-size:12px;color:var(--text-muted);margin-top:2px">${it.label}</div>
                    </div>
                </div>
            </div>`).join('');
    },

    // ---- 阶段进度可视化 ----
    initPhaseProgress(){
        const phases = [
            { id:'p1', name:'合规闸门', desc:'禁词过滤 / AI标识注入' },
            { id:'p2', name:'意图路由', desc:'语义分析 / 平台分发决策' },
            { id:'p3', name:'内容工厂', desc:'JSON-LD生成 / TL;DR摘要' },
            { id:'p4', name:'API推送', desc:'微信/抖音/百度分发' },
            { id:'p5', name:'监控记录', desc:'引用率追踪 / 告警' },
        ];
        document.getElementById('phaseProgress').innerHTML = phases.map((p,i)=>`
            <div class="pp-phase" id="pp-${i}">
                <div class="pp-indicator">
                    <div class="pp-dot">${i+1}</div>${i<phases.length-1?'<div class="pp-line"></div>':''}
                </div>
                <div class="pp-body">
                    <div class="pp-name">${p.name}</div>
                    <div class="pp-detail">${p.desc}</div>
                    <div class="pp-time" id="pp-time-${i}"></div>
                </div>
            </div>
        `).join('');
    },

    /** [H-03] 设置单个阶段视觉状态 */
    setWfPhase(idx, status){
        const el = document.getElementById(`pp-${idx}`);
        if(!el) return;
        el.className = 'pp-phase '+ (status==='done'?'done':status==='running'?'running':'');
        const t = document.getElementById(`pp-time-${idx}`);
        if(t) t.textContent = status==='done'?'已完成':status==='running'?'正在处理...':'';
    },

    updatePhaseSim(attempt){
        const phaseIdx = Math.min(Math.floor(attempt/6),4);
        for(let i=0;i<=phaseIdx;i++){
            this.setWfPhase(i, i<phaseIdx ? 'done' : 'running');
        }
        for(let i=phaseIdx+1;i<=4;i++){
            this.setWfPhase(i, '');
        }
    },

    setAllPhasesDone(ok){
        for(let i=0;i<=4;i++){
            const el = document.getElementById(`pp-${i}`);
            if(el) el.className = ok ? 'pp-phase done' : 'pp-phase error';
            const t = document.getElementById(`pp-time-${i}`);
            if(t) t.textContent = ok ? '已完成' : '失败';
        }
    },

    /** [W1] 渲染 CSV 数据预览表格 */
    _renderCsvPreview(uploadResp){
        if(!uploadResp.preview_headers || !uploadResp.preview_count){
            toggleEl('csvPreviewCard', false); return;
        }
        
        // 表头
        const headers = uploadResp.preview_headers;
        document.getElementById('csvPreviewHead').innerHTML =
            '<tr>' + headers.map(h => `<th style="font-size:12px;">${h}</th>`).join('') + '</tr>';
        
        // 预览数据（从上传响应中取前10条，如果有的话；否则显示空行提示）
        let bodyHtml = '';
        if(Array.isArray(uploadResp.preview_data) && uploadResp.preview_data.length){
            uploadResp.preview_data.slice(0,10).forEach((row) => {
                bodyHtml += '<tr>' + headers.map(h =>
                    `<td style="font-size:12px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(row[h])||''}">${esc(row[h])||'-'}</td>`
                ).join('') + '</tr>';
            });
        } else {
            bodyHtml = `<tr><td colspan="${headers.length}" style="text-align:center;color:var(--text-muted);padding:16px;">
                ✅ 文件解析成功 (${uploadResp.preview_count} 条记录)，点击「开始执行 GEO 流水线」处理全部数据
            </td></tr>`;
        }
        document.getElementById('csvPreviewBody').innerHTML = bodyHtml;
        document.getElementById('csvPreviewCount').textContent = `${uploadResp.preview_count} 条记录`;
        toggleEl('csvPreviewCard', true);
    }
};


// ============================================================
//  PAGE 2: JOBS (增强版: 删除/详情/分类筛选/防抖)
// ============================================================
var Jobs = window.Jobs = {
    _debounceTimer: null,
    _currentJob: null,   // [J2] 当前查看的岗位详情
    _currentPage: 1,
    _categoriesLoaded: false,
    /** 刷新列表（供404错误页的"刷新"按钮调用） */
    _refreshList(){ this.load(Jobs._currentPage||1); },
    async load(page=1){
        this._currentPage = page;
        
        // [J4] 获取分类筛选（首次加载时获取分类列表）
        if(!this._categoriesLoaded){
            await this._loadCategories();
        }
        const catFilter = document.getElementById('jobCategoryFilter')?.value||'';
        const q = document.getElementById('jobSearch')?.value||'';
        let url = `/api/jobs?page=${page}&per_page=20&search=${encodeURIComponent(q)}`;
        if(catFilter) url += `&category=${encodeURIComponent(catFilter)}`;

        const r = await API.get(url);

        if(!r.ok||!r.data){
            document.getElementById('jobsBody').innerHTML='<tr><td colspan="8" class="empty-state">暂无数据</td></tr>';
            return;
        }

        const rows=r.data.data||[];
        
        document.getElementById('jobsBody').innerHTML=rows.map((j,i)=>`
            <tr data-source="${j.data_source||'unknown'}">
                <td><code style="font-size:11px">${esc(j.id)||(page-1)*20+i+1}</code></td>
                <td>
                    <div style="display:flex;align-items:center;gap:4px;">
                        <strong style="cursor:pointer;color:var(--primary);" onclick="Jobs.showDetail('${encodeURIComponent(esc(j.id))}')" title="点击查看详情">${esc(j.title)||'-'}</strong>
                        ${j.data_source === 'csv' ? '<span class="tag" style="background:#f59e0b;color:#fff;font-size:9px;padding:1px 4px;border-radius:3px;">CSV</span>' : ''}
                        ${j.data_source === 'sqlite' ? '<span class="tag" style="background:#10b981;color:#fff;font-size:9px;padding:1px 4px;border-radius:3px;">DB</span>' : ''}
                    </div>
                </td>
                <td>${esc(j.company)||'-'}</td>
                <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px">${esc(j.location)||'-'}</td>
                <td class="salary-text">¥${j.min_salary||0}-¥${j.max_salary||0}</td>
                <td><span class="tag tag-blue">${esc(j.category)||'-'}</span></td>
                <td>${j.is_urgent?'<span class="tag tag-red">急招</span>':'<span style="color:var(--text-muted)">否</span>'}</td>
                <td>
                    <div style="display:flex;gap:4px;">
                        <button class="btn-outline btn-sm" onclick="Schema.fromJob('${encodeURIComponent(esc(j.title))}')" title="Schema预览">预览</button>
                        <button class="btn-outline btn-sm" onclick="Jobs.showDetail('${encodeURIComponent(esc(j.id))}')" title="查看详情">详情</button>
                        <!-- [J1] 删除按钮 -->
                        <button class="btn-outline btn-sm" style="color:#dc2626;border-color:#dc2626;" onclick="Jobs.deleteJob(${jsStr(j.id)},${jsStr(esc(j.title))})"
                            title="删除此岗位">🗑</button>
                    </div>
                </td>
            </tr>`).join('');
        
        // 在表头添加来源指示器
        const thead = document.querySelector('#page-jobs table thead tr');
        if(thead && !thead.querySelector('.source-col')){
            thead.innerHTML = '<th style="width:50px">ID</th><th>岗位名称</th><th>企业</th><th>地点</th><th>薪资</th><th>分类</th><th>状态</th><th style="width:180px">操作</th>';
        }
        
        renderPg(r.data.pagination,'jobsPagination',Jobs.load);
    },

    /** 加载分类列表到筛选下拉框 */
    async _loadCategories(){
        if(this._categoriesLoaded) return;
        try {
            const r = await API.get('/api/stats');
            if(r.ok && r.data?.categories){
                const sel = document.getElementById('jobCategoryFilter');
                if(sel){
                    const cats = Object.entries(r.data.categories);
                    if(cats.length > 0){
                        // 保留"全部分类"选项，在前面插入分类
                        const allOpt = sel.querySelector('option[value=""]') || sel.options[0];
                        sel.innerHTML = allOpt ? `<option value="">全部分类</option>` : '';
                        cats.sort((a,b) => b[1] - a[1]).forEach(([cat, count]) => {
                            if(cat && cat !== 'general'){
                                sel.innerHTML += `<option value="${esc(cat)}">${esc(cat)} (${count})</option>`;
                            }
                        });
                    }
                }
            }
        } catch(e) { /* 静默失败，使用默认选项 */ }
        this._categoriesLoaded = true;
    },

    /** [J3] 防抖搜索 */
    searchDebounce(){
        clearTimeout(this._debounceTimer);
        this._debounceTimer = setTimeout(()=>this.load(1), 350);
    },

    /** [J1] 删除岗位 */
    async deleteJob(id, title){
        if(!confirm(`确定删除岗位「${title}」吗？此操作不可撤销。`)) return;

        try{
            // [M-01 fix] 移除冗余的 POST 请求，仅使用标准 DELETE 方法
            const delR = await fetch(`/api/job/${id}`, { method: 'DELETE' });
            
            if(delR.ok || delR.status===204){
                toast('已删除','success');
                this.load(1); // 刷新列表
            } else {
                const err = await delR.json().catch(() => ({}));
                toast(err.error || '删除失败', 'error');
            }
        }catch(e){
            toast('删除失败: '+e.message,'error');
        }
    },

    /** [J2] 显示岗位详情弹窗 */
    async showDetail(jobIdEnc){
        const jobId = decodeURIComponent(jobIdEnc);
        this._currentJob = null;

        const body = document.getElementById('jobDetailBody');
        body.innerHTML = '<p style="text-align:center;padding:30px;color:var(--text-muted);"><span style="animation:spin-dot 1s infinite;display:inline-block;">⏳</span> 加载中...</p>';
        
        // 显示弹窗
        const modal = document.getElementById('jobDetailModal');
        modal.classList.remove('hidden');
        // [A-02] 焦点陷阱: 记录之前聚焦的元素，便于关闭时恢复
        this._prevFocus = document.activeElement;
        
        // [A-02] 绑定ESC键关闭
        this._escHandler = (e) => { if(e.key === 'Escape') this.closeDetail(); };
        document.addEventListener('keydown', this._escHandler);

        try{
            const r = await API.get(`/api/job/${jobId}`);

            // [R-06] 区分404(数据不一致)与网络错误，提供针对性引导
            if(!r.ok || !r.data){
                const is404 = (r.status === 404) || (!r.data && String(r.status).startsWith('4'));
                if(is404){
                    body.innerHTML = `
                        <div style="text-align:center;padding:30px;">
                            <div style="font-size:48px;margin-bottom:12px;">🔍</div>
                            <div style="font-size:16px;font-weight:600;color:var(--danger);margin-bottom:8px;">岗位不存在或已被删除</div>
                            <div style="font-size:13px;color:var(--text-muted);margin-bottom:20px;">
                                ID: <code>${esc(jobId)}</code> 在数据库中未找到<br>
                                <span style="font-size:12px;">可能原因：数据已清理 / 列表缓存与数据库不同步</span>
                            </div>
                            <button class="btn-outline btn-sm" onclick="Jobs.closeDetail(); Jobs._refreshList(); this.disabled=true">
                                🔄 刷新岗位列表
                            </button>
                        </div>`;
                } else {
                    body.innerHTML = `<p style="color:var(--danger);text-align:center;">请求失败 (${r.status||'未知错误'})</p>`;
                }
                return;
            }

            const j = r.data;
            this._currentJob = j;

            document.getElementById('jobDetailTitle').textContent = j.title || '岗位详情';

            // 数据来源标签样式
            const sourceTag = j.data_source === 'sqlite' 
                ? `<span style="background:#10b981;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;">📦 数据库</span>`
                : `<span style="background:#f59e0b;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;margin-left:8px;">📄 CSV</span>`;
            
            // 源文件信息
            const sourceFile = j.source_file ? `<span style="font-size:11px;color:var(--text-muted);">(${j.source_file})</span>` : '';

            // 渲染详情字段（区分纯文本和HTML字段）
            const plainFields = [
                ['ID', j.id, false], 
                ['企业', j.company, false],
                ['地点', j.location, false], 
                ['最低薪资', `¥${j.min_salary||0}`, false],
                ['最高薪资', `¥${j.max_salary||0}`, false], 
                ['分类', j.category, false],
                ['急招', j.is_urgent ? '是' : '否', false], 
            ];
            const htmlFields = [
                ['标题', j.title + sourceTag, true],
                ['要求', j.requirements, true],
                ['福利', j.benefits, true],
                ['数据来源', (j.data_source === 'sqlite' ? '📦 SQLite 数据库' : '📄 CSV 文件') + sourceFile, true],
            ];

            body.innerHTML = plainFields.map(([label, val, isHtml]) => `
                <div class="job-detail-field">
                    <span class="job-detail-label">${label}</span>
                    <span class="job-detail-value">${isHtml ? val : esc(val)||'-'}</span>
                </div>
            `).join('') + 
            htmlFields.map(([label, val, isHtml]) => `
                <div class="job-detail-field">
                    <span class="job-detail-label">${label}</span>
                    <span class="job-detail-value" style="white-space:pre-wrap;">${val || '-'}</span>
                </div>
            `).join('') + `<input type="hidden" id="jobDetailRawTitle" value="${esc(j.title)}">
                         <input type="hidden" id="jobDetailRawId" value="${esc(j.id)}">`;

        }catch(e){
            body.innerHTML = `<p style="color:var(--danger);text-align:center;">加载失败: ${e.message}</p>`;
        }
    },

    closeDetail(event){
        // 仅当点击 overlay 背景或关闭按钮时关闭
        if(!event || event.target === event.currentTarget){
            document.getElementById('jobDetailModal').classList.add('hidden');
            this._currentJob = null;
            // [A-02] 解绑ESC监听
            if(this._escHandler){ document.removeEventListener('keydown', this._escHandler); this._escHandler = null; }
            // [A-02] 恢复焦点到触发元素
            if(this._prevFocus && typeof this._prevFocus.focus === 'function'){ this._prevFocus.focus(); this._prevFocus = null; }
        }
    }
};

// Schema.fromJob moved after Schema declaration (line ~460) to fix TDZ error


// ============================================================
//  PAGE 3: SCHEMA (增强版: 多Schema类型 + 快速模板 + 全字段填充)
// ============================================================
var Schema = window.Schema = {
    _currentType: 'jobposting',   // [S1] 当前 Schema 类型
    _busy: false,                  // [防重复点击] 生成锁

    async generate(){
        if(this._busy) return;
        this._busy = true;
        const btn = document.querySelector('[onclick="Schema.generate()"]');
        if(btn){btn.disabled=true;btn.textContent='⏳ 生成中...';}

        try {
            if(this._currentType !== 'jobposting'){
                await this._generateAlt();
                return;
            }

            const p=new URLSearchParams({
                title:document.getElementById('schemaTitle')?.value||'',
                company:document.getElementById('schemaCompany')?.value||'',
                location:document.getElementById('schemaLocation')?.value||'',
                min_salary:document.getElementById('schemaMinSalary')?.value||0,
                max_salary:document.getElementById('schemaMaxSalary')?.value||0,
                requirements:document.getElementById('schemaReq')?.value||'', benefits:''
            });

            const r=await fetch(`/api/schema-preview?${p}`);
            const d=await r.json();
            document.getElementById('schemaOutput').textContent=JSON.stringify(d,null,2);

            // SEO checklist
            const tips=document.getElementById('seoTips');
            tips.innerHTML=`
                <div style="padding:6px 0;font-size:13px">
                    ${checkRow('title',!!d.title,'title 必填且含地理关键词')}
                    ${checkRow('hiringOrganization',!!d.hiringOrganization?.name,'企业名称必填')}
                    ${checkRow('jobLocation',!!d.jobLocation?.address?.streetAddress,'详细地址(LBS锚点)必填')}
                    ${checkRow('baseSalary',!!d.baseSalary?.value,'薪资信息(提升引用率~23%)')}
                </div>
                <p style="color:var(--text-muted);font-size:11px;margin-top:8px;">
                    💡 生成的 JSON-LD 放入 &lt;head&gt; 的 &lt;script type="application/ld+json"&gt; 标签内
                </p>`;
        }catch(e){toast('生成失败:'+e.message,'error');}
        finally{
            this._busy = false;
            if(btn){btn.disabled=false;btn.textContent='生成 JSON-LD 结构化数据';}
        }
    },

    /** [S1] 切换 Schema 类型 */
    switchType(type){
        this._currentType = type;
        
        // 更新标签激活状态
        document.querySelectorAll('.schema-tab').forEach(btn => {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-outline');
            if(btn.dataset.type === type){
                btn.classList.remove('btn-outline');
                btn.classList.add('btn-primary');
            }
        });

        // 切换显示区域
        if(type === 'jobposting'){
            toggleEl('schemaJobArea', true);
            toggleEl('schemaAltArea', false);
        } else {
            toggleEl('schemaJobArea', false);
            toggleEl('schemaAltArea', true);
            this._renderAltInputs(type);
        }
    },

    /** [S1] 渲染非 JobPosting 类型的输入表单 */
    _renderAltInputs(type){
        const area = document.getElementById('schemaAltInputs');
        const titleEl = document.getElementById('schemaAltInputTitle');

        const templates = {
            organization: {
                title: 'Organization / LocalBusiness 参数',
                fields: [
                    {key:'name', label:'企业名称', value:'021kp松江快聘', type:'text'},
                    {key:'description', label:'企业描述', value:'松江区域专业招聘服务平台，专注G60科创走廊人才服务', type:'textarea'},
                    {key:'address', label:'详细地址', value:'上海市松江区G60科创云廊', type:'text'},
                    {key:'lat', label:'纬度', value:'31.0376', type:'number'},
                    {key:'lng', label:'经度', value:'121.2345', type:'number'},
                ],
            },
            faq: {
                title: 'FAQPage 常见问题参数',
                fields: [
                    {key:'topic', label:'FAQ 主题', value:'松江招聘常见问题', type:'text'},
                    {key:'job_id', label:'关联岗位ID (可选)', value:'', type:'text'},
                ],
            },
            breadcrumb: {
                title: 'BreadcrumbList 导航参数',
                fields: [
                    {key:'page_path', label:'页面路径', value:'detail', type:'select',
                     options:['home','jobs','detail','about','contact']},
                ],
            }
        };

        const tpl = templates[type];
        if(!tpl) return;
        
        titleEl.textContent = tpl.title;

        let html = '';
        tpl.fields.forEach(f => {
            if(f.type === 'select'){
                html += `<div class="form-group"><label class="form-label">${f.label}</label><select class="select" id="alt_${f.key}">`;
                (f.options||[]).forEach(opt => {
                    html += `<option value="${opt}" ${opt === f.value ? 'selected' : ''}>${opt}</option>`;
                });
                html += `</select></div>`;
            } else if(f.type === 'textarea'){
                html += `<div class="form-group"><label class="form-label">${f.label}</label><textarea class="textarea" id="alt_${f.key}">${f.value}</textarea></div>`;
            } else {
                html += `<div class="form-group"><label class="form-label">${f.label}</label><input type="${f.type}" class="input" id="alt_${f.key}" value="${f.value}"></div>`;
            }
        });

        html += `<button class="btn-primary" onclick="Schema._generateAlt()">生成 JSON-LD</button>`;

        area.innerHTML = html;
    },

    /** [S1] 生成非 JobPosting 类型 Schema */
    async _generateAlt(){
        let url = '';
        const type = this._currentType;

        if(type === 'organization'){
            url = '/api/geo/org-schema';
        } else if(type === 'faq'){
            const topic = document.getElementById('alt_topic')?.value || '';
            const jobId = document.getElementById('alt_job_id')?.value || '';
            url = `/api/geo/faq-schema?topic=${encodeURIComponent(topic)}${jobId ? '&job_id='+encodeURIComponent(jobId) : ''}`;
        } else if(type === 'breadcrumb'){
            const pp = document.getElementById('alt_page_path')?.value || 'home';
            url = `/api/geo/breadcrumb?page_path=${encodeURIComponent(pp)}`;
        }

        try{
            const r = await fetch(url);
            const d = await r.json();
            
            let output = {};
            if(type === 'organization'){
                output = {organization: d.organization, local_business: d.local_business, geo_layer: d.geo_layer};
            } else {
                output = d;
            }
            
            document.getElementById('schemaAltOutput').textContent = JSON.stringify(output, null, 2);
            document.getElementById('schemaAltCopyBtn').disabled = false;
            toast(`${type.toUpperCase()} Schema 已生成`,'success');
        }catch(e){
            toast('生成失败:'+e.message,'error');
        }
    },

    copyAlt(){
        const text = document.getElementById('schemaAltOutput')?.textContent||'';
        this._safeCopy(text);
    },

    copy(){
        const text = document.getElementById('schemaOutput')?.textContent||'';
        this._safeCopy(text);
    },

    /** [安全] 统一复制逻辑 — 带 fallback 降级 */
    _safeCopy(text){
        if(navigator.clipboard && window.isSecureContext){
            navigator.clipboard.writeText(text)
                .then(()=>toast('已复制到剪贴板','success'))
                .catch(()=>this._fallbackCopy(text));
        } else {
            this._fallbackCopy(text);
        }
    },
    _fallbackCopy(text){
        try{
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position='fixed';ta.style.left='-9999px';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            ta.remove();
            toast('已复制到剪贴板','success');
        }catch(e){
            toast('复制失败，请手动选择文本复制','error');
        }
    },

    /** [S3] 快速行业模板填充 */
    applyTemplate(template){
        const tpls = {
            manufacturing:{title:'松江九亭 CNC数控操作员',company:'上海智能装备制造有限公司',location:'上海市松江区洞泾镇沈砖公路538号智能制造园',min:7000,max:12000,req:'1.中专及以上学历，机械或数控相关专业\n2.熟练操作法兰克/西门子系统\n3.能看懂图纸，有加工中心经验优先\n4.吃苦耐劳，适应两班倒'},
            it:{title:'松江G60园区 高级Python工程师',company:'上海智能装备制造有限公司',location:'上海市松江区洞泾镇沈砖公路538号智能制造园',min:15000,max:28000,req:'1.本科及以上学历,计算机相关专业\n2.3年以上Python后端开发经验\n3.熟悉Django/Flask框架\n4.有高并发项目经验优先'},
            logistics:{title:'松江物流园 仓储主管',company:'上海智联供应链管理有限公司',location:'上海市松江区车墩镇北松公路4899号物流园区',min:8000,max:13000,req:'1.大专及以上学历，物流管理相关专业\n2.3年以上仓储管理经验\n4.熟悉WMS系统操作\n5.具备团队管理能力'},
            ecommerce:{title:'松江电商运营专员',company:'松江新零售科技有限公司',location:'上海市松江区中山街道茸平路118号电商大厦',min:9000,max:16000,req:'1.本科及以上学历，市场营销/电子商务专业\n2.1年以上电商运营经验(抖音/淘宝/京东)\n3.熟悉数据分析工具\n4.有直播电商运营经验优先'},
            hr:{title:'松江HR招聘专员',company:'上海人力资源服务有限公司',location:'上海市松江区广富林路658弄万达广场B座',min:8000,max:14000,req:'1.本科及以上学历，人力资源管理专业\n2.2年以上招聘或HRBP经验\n3.熟悉劳动法规及社保政策\n4.沟通能力强，有制造业招聘背景优先'}
        };
        const t = tpls[template];
        if(!t) return;
        document.getElementById('schemaTitle').value = t.title;
        document.getElementById('schemaCompany').value = t.company;
        document.getElementById('schemaLocation').value = t.location;
        document.getElementById('schemaMinSalary').value = t.min;
        document.getElementById('schemaMaxSalary').value = t.max;
        document.getElementById('schemaReq').value = t.req;
        toast(`已加载「${template}」模板`,'info');
    }
};

/** [S2] fromJob — 支持从列表预览时先拉取全量数据 */
Schema.fromJob = async function(t) {
    const title = decodeURIComponent(t);
    let jobData = Jobs._currentJob;

    // [M-03] 如果没有缓存的全量数据（用户未打开详情弹窗），尝试通过标题匹配
    if(!jobData || !jobData.title){
        try{
            // 从岗位列表中搜索匹配的岗位（避免额外API调用）
            const listR = await API.get(`/api/jobs?per_page=200&search=${encodeURIComponent(title)}`);
            const found = (listR.data?.data||[]).find(j => j.title === title || j.id === title);
            if(found) jobData = found;
        }catch(e){/* 降级到仅填充标题 */ }
    }

    if(jobData && jobData.title){
        document.getElementById('schemaTitle').value = jobData.title || title;
        document.getElementById('schemaCompany').value = jobData.company || '';
        document.getElementById('schemaLocation').value = jobData.location || '';
        document.getElementById('schemaMinSalary').value = jobData.min_salary || 0;
        document.getElementById('schemaMaxSalary').value = jobData.max_salary || 0;
        document.getElementById('schemaReq').value = jobData.requirements || jobData.description || '';
    } else {
        document.getElementById('schemaTitle').value = title;
    }

    this.switchType('jobposting');
    switchPage('schema');
    Schema.generate();
};

function checkRow(_field, ok, text){
    const color = ok ? 'var(--success)' : 'var(--danger)';
    return `<p style="color:${color};padding:3px 0;">${ok?'✅':'❌'} ${text}</p>`;
}


// ============================================================
//  PAGE 4: MONITOR (增强版 - 集成 Phase 5 dist_monitor)
// ============================================================
var Monitor = window.Monitor = {
    _citationData: null,
    _alertsData: null,
    _autoRefreshTimer: null,   // [L-02] 自动刷新定时器

    /** 骨架屏切换：隐藏骨架占位，显示真实容器 */
    _switchToReal(realId, skeletonId){
        const skeleton = document.getElementById(skeletonId);
        const real = document.getElementById(realId);
        if(skeleton) skeleton.classList.add('hidden');
        if(real) real.classList.remove('hidden');
    },

    async load(){
        this._startAutoRefresh(); // [L-02] 启动自动刷新
        // 并行加载所有数据源
        const [sr, str, hr, citation, alerts, rollback, reports] = await Promise.allSettled([
            API.get('/api/status'),
            API.get('/api/stats'),
            API.get('/api/history'),
            API.get('/api/monitor/citation'),   // F1: 引用率
            API.get('/api/monitor/alerts?days=7'),// F2: 告警中心
            API.get('/api/monitor/rollback'),    // F3: 回滚状态
            API.get('/api/monitor/reports?limit=8') // F4: 报告列表
        ]);

        this._renderBasicStats(sr, str);
        if(hr.status==='fulfilled')this._renderHistory(hr.value.data||{});
        if(citation.status==='fulfilled')this._renderCitationPanel(citation.value.data||{});
        if(alerts.status==='fulfilled')this._renderAlertsPanel(alerts.value.data||{});
        if(rollback.status==='fulfilled')this._renderRollbackPanel(rollback.value.data||{});
        if(reports.status==='fulfilled')this._renderReportsPanel(reports.value.data||{});
    },

    /** [M-05] 增强版条形图 — 支持百分比标签、动画过渡、颜色分级 */
    _renderEnhancedBar(_containerId, label, value, max, gradient, unit='') {
        const pct = max > 0 ? Math.round(value / max * 100) : 0;
        const color = pct >= 80 ? '#059669' : pct >= 50 ? '#2563eb' : '#d97706';
        return `<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
            <span style="min-width:55px;font-size:12px;">${label}</span>
            <div style="flex:1;height:22px;background:var(--gray-100);border-radius:4px;overflow:hidden;position:relative;">
                <div style="height:100%;width:${pct}%;background:linear-gradient(90deg,${gradient});border-radius:4px;transition:width 0.5s ease;"></div>
                <span style="position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:10px;font-weight:600;color:var(--text-muted);">${pct}%</span>
            </div>
            <span style="min-width:45px;text-align:right;font-size:12px;font-weight:600;color:${color};">${value}${unit}</span>
        </div>`;
    },

    /** F1: 渲染 AI 引用率监控面板 */
    _renderCitationPanel(data){
        this._citationData = data;
        const metrics = data.metrics || [];

        // 整体状态徽章
        const statusEl = document.getElementById('citationOverallStatus');
        const statusMap = { NORMAL:'正常', DEGRADED:'降级', FROZEN:'已冻结' };
        const statusCls = { NORMAL:'tag-green', DEGRADED:'tag-blue', FROZEN:'tag-red' };
        statusEl.textContent = statusMap[data.overall_status]||'未知';
        statusEl.className = `tag ${statusCls[data.overall_status]||'tag-gray'}`;

        if(metrics.length===0){
            // 骨架屏切换
            this._switchToReal('citationMetricsGrid', 'citationMetricsGridSkeleton');
            document.getElementById('citationMetricsGrid').innerHTML=
                '<div style="grid-column:1/-1;color:var(--text-muted);font-size:13px;text-align:center;padding:30px 0;">暂无检测数据，点击「执行引用率检测」获取</div>';
            document.getElementById('citationTrendSummary').style.display='none';
            return;
        }
        
        // 骨架屏切换：隐藏骨架，显示真实容器
        this._switchToReal('citationMetricsGrid', 'citationMetricsGridSkeleton');

        // 平台颜色映射
        const platformColors = {
            'deepseek': '#0066cc',
            'doubao': '#4a90d9',
            'yuanbao': '#ff6b35',
            'tongyi': '#ff6a00',
            'wenxin': '#00a0e9',
            'kimi': '#6c5ce7',
            'zhipu': '#00d4aa',
            'metaso': '#1a73e8',
            'nami': '#e91e63',
        };
        const platformNames = {
            'deepseek': 'DeepSeek 深度求索',
            'doubao': '豆包',
            'yuanbao': '元宝',
            'tongyi': '通义千问',
            'wenxin': '文心一言',
            'kimi': 'Kimi',
            'zhipu': '智谱清言',
            'metaso': '秘塔 AI',
            'nami': '纳米 AI',
        };
        const trendIcons={rising:'\u2197',stable:'\u2192',falling:'\u2198',unknown:'?'};
        const trendLabels={rising:'上升',stable:'稳定',falling:'下降',unknown:'未知'};
        
        document.getElementById('citationMetricsGrid').innerHTML=metrics.map(m=>{
            const pct=m.citation_rate;
            const color=pct>=1?'#059669':pct>=0.5?'#d97706':'#dc2626';
            const borderColor=platformColors[m.platform]||color;
            const name=platformNames[m.platform]||m.platform;
            return `
            <div class="phase-card" style="border-left:3px solid ${borderColor};cursor:pointer;" 
                 onclick="Monitor.showPlatformDetail('${esc(m.platform)}')" 
                 title="点击查看 ${name} 详细数据">
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-weight:600;font-size:14px;">${esc(name)}</span>
                    <span style="font-size:10px;color:${borderColor};font-weight:600;background:rgba(0,0,0,0.05);padding:2px 6px;border-radius:4px;">${esc(m.platform.toUpperCase())}</span>
                </div>
                <div style="display:flex;align-items:baseline;gap:4px;margin:8px 0;">
                    <span style="font-size:28px;font-weight:800;color:${color}">${pct.toFixed(2)}</span>
                    <span style="font-size:12px;color:var(--text-muted);">%</span>
                    <span style="font-size:12px;color:${m.trend==='rising'?'#059669':m.trend==='falling'?'#dc2626':'var(--text-muted)'};" title="${trendLabels[m.trend]||'未知'}">${trendIcons[m.trend]||'?'}</span>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);">
                    <span>提及 ${m.brand_mention_count} 次</span>
                    <span>查询 ${m.total_queries}</span>
                </div>
                ${pct<0.5?`<div style="margin-top:6px;font-size:11px;color:#dc2626;">⚠ 低于阈值(0.5%)</div>`:''}
                <div style="margin-top:8px;font-size:11px;color:var(--primary);text-align:center;">点击查看详情 →</div>
            </div>`}).join('');

        // 趋势摘要
        const avg=data.avg_citation_rate||0;
        const summaryEl=document.getElementById('citationTrendSummary');
        summaryEl.style.display='';
        summaryEl.innerHTML=`<strong>摘要:</strong> 共监测 ${metrics.length} 个平台，`+
            `总提及 <strong>${data.total_brand_mentions||0}</strong> 次，`+
            `加权平均引用率 <strong style="color:${avg>=1?'#059669':avg>=0.5?'#d97706':'#dc2626'}">${avg.toFixed(2)}%</strong>，`+
            `整体状态：<strong>${statusMap[data.overall_status]||'未知'}</strong> · `+
            `检测时间：${data.checked_at?data.checked_at.slice(5,16).replace('T',' '):'-'} · `+
            `${data.overall_status==='FROZEN'?'<span style="color:#dc2626;">⚡ 已触发自动回滚保护</span>':''}`;
    },

    /** F2: 渲染告警中心 */
    _renderAlertsPanel(data){
        this._alertsData = data;
        const alerts = data.alerts||[];
        const sc=data.severity_counts||{};
        
        document.getElementById('alertCriticalCount').textContent=`${sc.critical||0} Critical`;
        document.getElementById('alertWarningCount').textContent=`${sc.warning||0} Warning`;

        const body=document.getElementById('alertsPanelBody');
        if(!alerts.length){
            // 骨架屏切换
            this._switchToReal('alertsPanelBody', 'alertsPanelBodySkeleton');
            body.innerHTML='<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px 0;">✅ 近期无告警，系统运行正常</div>';
            return;
        }

        // 骨架屏切换：隐藏骨架，显示真实容器
        this._switchToReal('alertsPanelBody', 'alertsPanelBodySkeleton');
        
        const sevColors={critical:'#dc2626',warning:'#d97706',info:'#2563eb'};
        const sevTags={critical:'CRITICAL',warning:'WARNING',info:'INFO'};
        body.innerHTML=alerts.map(a=>`
            <div style="padding:10px;margin-bottom:8px;border-radius:8px;border-left:3px solid ${sevColors[a.severity]||'#999'};background:rgba(0,0,0,0.02);font-size:13px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                    <span class="tag tag-sm" style="background:${sevColors[a.severity]||'#999'};color:#fff;">${esc(sevTags[a.severity]||a.severity)}</span>
                    <strong style="flex:1;">${esc(a.rule)||'未知规则'}</strong>
                    <span style="color:var(--text-muted);font-size:11px;">${esc(a.timestamp?.slice(5,16))||''}</span>
                </div>
                <div style="color:var(--text-secondary)">${esc(a.message)||''}</div>
                <div style="margin-top:4px;font-size:11px;color:var(--text-muted);">当前值: ${a.current_value??'-'} / 阈值: ${a.threshold??'-'} → 建议: ${esc(a.action)||'-'}</div>
            </div>`).join('');
    },

    /** F3: 渲染回滚状态指示器 */
    _renderRollbackPanel(data){
        const rs=data.rollback_state||{};
        const body=document.getElementById('rollbackPanelBody');
        const isFrozen=rs.is_frozen;

        // 骨架屏切换：隐藏骨架，显示真实容器
        this._switchToReal('rollbackPanelBody', 'rollbackPanelBodySkeleton');

        body.innerHTML= isFrozen ? `
            <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
                <div style="font-size:36px;">🔒</div>
                <div>
                    <div style="font-size:18px;font-weight:700;color:#dc2626;">系统处于冻结状态 (Plan_C 合规模板)</div>
                    <div style="font-size:13px;color:var(--text-secondary);margin-top:4px;">
                        冻结原因: ${esc(rs.reason)||'未指定'}<br>
                        冻结时间: ${esc(rs.frozen_at)||'未知'}<br>
                        已冻结: ${rs.frozen_duration_hours||0} 小时<br>
                        可恢复: <strong style="color:${data.can_recover?'#059669':'#dc2626'}">${data.can_recover?'是 — '+esc(data.recovery_reason):'否'}</strong>
                    </div>
                </div>
            </div>` : `
            <div style="display:flex;align-items:center;gap:12px;color:var(--text-secondary);">
                <span style="font-size:28px;">✅</span>
                <div>
                    <div style="font-weight:600;color:#059669;">分发正常运行中，未触发回滚</div>
                    <div style="font-size:12px;margin-top:2px;">当 AI 引用率连续低于阈值(0.5%) 时，系统将自动切换至 Plan_C 安全模式</div>
                </div>
            </div>`;
        
        // 如果有最新回滚记录，追加显示
        if(data.latest_record){
            const lr=data.latest_record;
            body.innerHTML+=`
            <details style="margin-top:14px;">
                <summary style="cursor:pointer;font-size:12px;color:var(--primary);padding:4px 0;">查看最近一次回滚详情 (${lr.timestamp?.slice(0,10)||'N/A'})</summary>
                <pre style="background:var(--gray-50);padding:12px;border-radius:6px;font-size:11px;overflow:auto;max-height:180px;white-space:pre-wrap;">${JSON.stringify(lr,null,2)}</pre>
            </details>`;
        }
    },

    /** F4: 渲染监控报告列表 */
    _renderReportsPanel(data){
        const reports=data.reports||[];
        document.getElementById('reportsTotalHint').textContent=`共 ${data.total} 份`;
        const body=document.getElementById('reportsPanelBody');
        if(!reports.length){
            // 骨架屏切换
            this._switchToReal('reportsPanelBody', 'reportsPanelBodySkeleton');
            body.innerHTML='<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px 0;">暂无监控报告。执行引用率检测后将自动生成。</div>';
            return;
        }

        // 骨架屏切换：隐藏骨架，显示真实容器
        this._switchToReal('reportsPanelBody', 'reportsPanelBodySkeleton');

        const stColors={NORMAL:'#059669',DEGRADED:'#d97706',FROZEN:'#dc2626'};
        body.innerHTML=reports.map(r=>`
            <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-color);">
                <span style="min-width:80px;font-size:12px;font-family:monospace;">${esc(r.id.replace('report_',''))}</span>
                <span class="tag tag-sm" style="background:${stColors[r.overall_status]||'#999'};color:#fff;">${esc(r.overall_status)}</span>
                <span style="font-size:12px;flex:1;">${r.platforms_checked} 平台 · ${r.alerts_count} 告警</span>
                <span style="font-size:11px;color:var(--text-muted);">${r.file_size_kb} KB</span>
                ${r.has_markdown?'<span class="tag tag-sm tag-blue">MD</span>':''}
                <span style="font-size:11px;color:var(--text-muted);">${esc(r.generated_at?.slice(5,16))||''}</span>
            </div>`).join('');
    },

    /** 手动触发引用率检测 (F5) */
    async triggerCheck(){
        const btn=document.getElementById('manualCheckBtn');
        btn.disabled=true;btn.textContent='⏳ 检测中...';

        // 立即显示实时日志窗口
        LogWindow.show();
        LogWindow.log('🔄 检测已启动 - 开始执行引用率检测', 'INFO', 'System');

        // 更新面板为 loading 状态
        document.getElementById('citationMetricsGrid').innerHTML=
            '<div style="grid-column:1/-1;text-align:center;padding:30px 0;"><div style="animation:spin-dot 1s infinite;display:inline-block;">⏳</div><p style="color:var(--text-muted);margin-top:8px;">正在采集各平台引用率数据...</p></div>';
        document.getElementById('citationTrendSummary').style.display='none';

        // 添加初始日志
        LogWindow.log('📋 目标: 所有已启用的 AI 平台', 'INFO', 'System');

        let r = null;
        try{
            LogWindow.log('📡 发送 POST /api/monitor/check', 'DEBUG', 'Network');

            r=await API.post('/api/monitor/check');
            
            LogWindow.log(`📥 收到响应: status=${r.status}`, 'DEBUG', 'Network');

            const d=r.data||{};

            if(!r.ok){
                const errMsg = d.error||`请求失败 (${r.status})`;
                LogWindow.log(`❌ 请求失败: ${errMsg}`, 'ERROR', 'System');
                throw new Error(errMsg);
            }
            
            // 用返回数据更新 UI
            const citationData = {
                checked_at: d.generated_at,
                overall_status: d.status,
                metrics: d.metrics_summary || [],
                avg_citation_rate: d.metrics_summary?.length > 0 
                    ? d.metrics_summary.reduce((sum, m) => sum + (m.citation_rate || 0), 0) / d.metrics_summary.length 
                    : 0
            };
            this._renderCitationPanel(citationData);

            // 显示详细指标日志
            if(d.metrics_summary && d.metrics_summary.length > 0){
                LogWindow.log('📊 各平台检测结果:', 'INFO', 'Result');
                for(const m of d.metrics_summary){
                    LogWindow.log(`  [${m.platform}] 引用率: ${(m.citation_rate * 100).toFixed(2)}% | 提及: ${m.brand_mention_count}/${m.total_queries}`, 'DEBUG', 'Platform');
                }
            }

            // 根据结果显示提示
            const alertsCount = d.alerts_triggered ?? 0;
            if(d.rollback_executed){
                LogWindow.log(`⚠️ 触发回滚保护 | 状态: ${d.status} | ${alertsCount} 条告警`, 'WARN', 'System');
                toast(`⚠ 检测完成 | 状态: ${d.status||'未知'} | ${alertsCount} 条告警 | 已触发回滚保护`, 'warning');
            } else if(d.error){
                toast(`检测完成（部分数据）: ${d.error}`, 'warning');
            } else {
                LogWindow.log(`✅ 检测完成 | 状态: ${d.status} | ${alertsCount} 条告警`, 'INFO', 'Summary');
                toast(`✅ 检测完成 | 状态: ${d.status||'正常'} | ${alertsCount} 条告警`, 'success');
            }

            // 完成标记
            LogWindow.log('🎉 检测流程结束', 'INFO', 'System');

        }catch(e){
            LogWindow.log(`❌ 检测失败: ${e.message}`, 'ERROR', 'System');
            toast('检测失败: '+e.message, 'error');
            document.getElementById('citationMetricsGrid').innerHTML=
                '<div style="grid-column:1/-1;color:var(--text-muted);font-size:13px;text-align:center;padding:30px 0;">❌ 检测失败，请检查服务日志</div>';
        }finally{
            btn.disabled=false;btn.textContent='🔍 执行引用率检测';
        }
    },

    /** 显示 Debug 日志弹窗 */
    _showDebugLogModal(debugLogs, isLoading = false){
        // 移除已存在的弹窗
        const existing = document.getElementById('debugLogModal');
        if(existing) existing.remove();

        const html = `
        <div id="debugLogModal" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:2000;display:flex;align-items:center;justify-content:center;" onclick="Monitor._closeDebugLogModal(event)">
            <div style="background:white;border-radius:16px;width:95%;max-width:800px;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,0.3);" onclick="event.stopPropagation()">
                <!-- 头部 -->
                <div style="padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="font-size:24px;">🔧</span>
                        <div>
                            <h3 style="margin:0;font-size:16px;font-weight:600;">实时调试日志</h3>
                            <div style="font-size:11px;color:var(--text-muted);" id="debugLogCount">等待检测开始...</div>
                        </div>
                    </div>
                    <button onclick="Monitor._closeDebugLogModal()" style="width:32px;height:32px;border-radius:50%;border:none;background:var(--gray-100);cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;">×</button>
                </div>
                
                <!-- 日志内容 -->
                <div id="debugLogContent" style="flex:1;overflow:auto;padding:16px 20px;background:#f8fafc;min-height:400px;">
                    ${isLoading ? '<div style="text-align:center;padding:40px;color:var(--text-muted);"><div style="animation:spin-dot 1s infinite;display:inline-block;font-size:24px;">⏳</div><p style="margin-top:12px;">正在与各 AI 平台交互...</p></div>' : ''}
                </div>
                
                <!-- 底部状态栏 -->
                <div style="padding:10px 20px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:#f1f5f9;">
                    <div style="font-size:11px;color:#64748b;">
                        <span id="debugLogStatus">${isLoading ? '🔄 检测进行中...' : '✅ 检测完成'}</span>
                    </div>
                    <button onclick="Monitor._closeDebugLogModal()" style="padding:6px 16px;border-radius:6px;border:none;background:#2563eb;color:white;cursor:pointer;font-size:12px;font-weight:500;">关闭</button>
                </div>
            </div>
        </div>`;

        document.body.insertAdjacentHTML('beforeend', html);
        
        // 如果有初始日志，渲染它们
        if(debugLogs.length > 0){
            this._renderDebugLogs(debugLogs);
        }
    },

    /** 追加单条日志 */
    _appendDebugLog(message, level, step, data){
        const content = document.getElementById('debugLogContent');
        if(!content) return;

        const levelColors = {
            'DEBUG': {bg: '#f1f5f9', text: '#64748b', border: '#e2e8f0'},
            'INFO': {bg: '#e0f2fe', text: '#0369a1', border: '#bae6fd'},
            'WARN': {bg: '#fef3c7', text: '#92400e', border: '#fde68a'},
            'ERROR': {bg: '#fef2f2', text: '#991b1b', border: '#fecaca'}
        };
        const colors = levelColors[level] || levelColors['DEBUG'];

        const stepIcons = {
            'System': '⚙️',
            'Network': '🌐',
            'Platform': '🤖',
            'Result': '📊',
            'Summary': '📋'
        };
        const icon = stepIcons[step] || '📌';

        const dataStr = data && Object.keys(data).length > 0 
            ? `<div style="margin-top:8px;padding:10px;background:white;border-radius:6px;font-size:11px;line-height:1.6;color:#475569;border-left:3px solid ${colors.border};max-height:150px;overflow:auto;">${Object.entries(data).map(([k,v]) => `<div><strong style="color:#0369a1;">${k}:</strong> ${typeof v === 'object' ? JSON.stringify(v, null, 2) : v}</div>`).join('')}</div>` 
            : '';

        const time = new Date().toLocaleTimeString('zh-CN', {hour12: false}) + '.' + String(Date.now() % 1000).padStart(3, '0');
        
        const logHtml = `
        <div style="margin-bottom:12px;padding:12px;background:${colors.bg};border-radius:8px;border-left:4px solid ${colors.text};animation:_fadeIn 0.3s ease;">
            <div style="display:flex;align-items:flex-start;gap:10px;">
                <span style="font-size:18px;">${icon}</span>
                <div style="flex:1;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
                        <span style="font-size:10px;color:#94a3b8;font-family:monospace;">${time}</span>
                        <span style="font-size:10px;color:white;font-weight:600;background:${colors.text};padding:2px 8px;border-radius:4px;">${level}</span>
                        <span style="font-size:11px;font-weight:600;color:#334155;">${step}</span>
                    </div>
                    <div style="font-size:13px;color:#1e293b;line-height:1.5;word-break:break-all;">${esc(message)}</div>
                    ${dataStr}
                </div>
            </div>
        </div>`;

        // 移除 loading 状态
        const loadingDiv = content.querySelector('.loading-state');
        if(loadingDiv) loadingDiv.remove();

        content.insertAdjacentHTML('beforeend', logHtml);
        
        // 自动滚动到底部
        content.scrollTop = content.scrollHeight;
        
        // 更新计数
        const countEl = document.getElementById('debugLogCount');
        const statusEl = document.getElementById('debugLogStatus');
        if(countEl) countEl.textContent = `日志条数: ${content.children.length}`;
        if(statusEl) statusEl.textContent = '🔄 检测进行中...';
    },

    /** 渲染多条日志 */
    _renderDebugLogs(debugLogs){
        for(const log of debugLogs){
            this._appendDebugLog(log.message, log.level, log.step, log.data);
        }
    },

    /** 关闭 Debug 日志弹窗 */
    _closeDebugLogModal(e){
        if(e && e.target !== e.currentTarget) return;
        const modal = document.getElementById('debugLogModal');
        if(modal) modal.remove();
    },

    /** 单独刷新回滚状态 */
    async loadRollback(){
        try{
            const r=await API.get('/api/monitor/rollback');
            this._renderRollbackPanel(r.data||{});
        }catch(e){toast('刷新失败:'+e.message,'error');}
    },

    /** 显示平台详情弹窗 */
    showPlatformDetail(platform){
        const data = this._citationData;
        if(!data || !data.metrics) return;
        
        const m = data.metrics.find(x=>x.platform===platform);
        if(!m) return;

        const platformNames = {
            'deepseek': 'DeepSeek 深度求索',
            'doubao': '豆包',
            'yuanbao': '元宝',
            'tongyi': '通义千问',
            'wenxin': '文心一言',
            'kimi': 'Kimi',
            'zhipu': '智谱清言',
            'metaso': '秘塔 AI',
            'nami': '纳米 AI',
        };
        const platformColors = {
            'deepseek': '#0066cc','doubao': '#4a90d9','yuanbao': '#ff6b35',
            'tongyi': '#ff6a00','wenxin': '#00a0e9','kimi': '#6c5ce7',
            'zhipu': '#00d4aa','metaso': '#1a73e8','nami': '#e91e63',
        };
        const trendLabels={rising:'📈 上升',stable:'➡️ 稳定',falling:'📉 下降',unknown:'❓ 未知'};
        const trendTips={
            rising:'该平台对您内容的引用率正在增长，表现良好',
            stable:'该平台引用率维持稳定，建议持续优化内容质量',
            falling:'引用率下降，建议检查内容是否被更新或需要优化',
            unknown:'趋势未知，需要更多数据积累'
        };

        const name=platformNames[platform]||platform;
        const color=platformColors[platform]||'#666';
        const pct=m.citation_rate;
        const healthColor=pct>=1?'#059669':pct>=0.5?'#d97706':'#dc2626';
        const healthLabel=pct>=1?'✅ 健康':pct>=0.5?'⚠️ 需关注':'🚨 告警';
        const healthTip=pct>=1?'引用率处于健康水平':pct>=0.5?'引用率偏低，建议优化内容':pct>0?'引用率过低，建议检查内容分发状态':'该平台暂无引用数据';

        const html=`
        <div style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:1000;display:flex;align-items:center;justify-content:center;" onclick="Monitor.closeModal(event)">
            <div style="background:white;border-radius:16px;width:90%;max-width:560px;max-height:85vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);" onclick="event.stopPropagation()">
                <!-- 头部 -->
                <div style="padding:20px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;">
                    <div style="width:48px;height:48px;border-radius:12px;background:${color};display:flex;align-items:center;justify-content:center;color:white;font-size:20px;font-weight:700;">${platform.charAt(0).toUpperCase()}</div>
                    <div style="flex:1;">
                        <h2 style="margin:0;font-size:18px;font-weight:600;">${esc(name)}</h2>
                        <div style="font-size:12px;color:var(--text-muted);">${esc(platform.toUpperCase())} · 检测时间: ${data.checked_at?data.checked_at.replace('T',' ').slice(0,19):'-'}</div>
                    </div>
                    <button onclick="Monitor.closeModal()" style="width:32px;height:32px;border-radius:50%;border:none;background:var(--gray-100);cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;">×</button>
                </div>
                
                <!-- 核心指标 -->
                <div style="padding:20px 24px;">
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px;">
                        <!-- 引用率 -->
                        <div style="background:linear-gradient(135deg,${healthColor}15 0%,${healthColor}08 100%);border-radius:12px;padding:20px;text-align:center;border:1px solid ${healthColor}30;">
                            <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">引用率</div>
                            <div style="font-size:42px;font-weight:800;color:${healthColor};line-height:1;">${pct.toFixed(2)}<span style="font-size:18px;">%</span></div>
                            <div style="margin-top:8px;font-size:12px;color:${healthColor};font-weight:600;">${healthLabel}</div>
                        </div>
                        <!-- 品牌提及 -->
                        <div style="background:#f0f9ff;border-radius:12px;padding:20px;text-align:center;border:1px solid #bae6fd;">
                            <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">品牌提及次数</div>
                            <div style="font-size:42px;font-weight:800;color:#0369a1;line-height:1;">${m.brand_mention_count}</div>
                            <div style="margin-top:8px;font-size:12px;color:#0369a1;">次</div>
                        </div>
                    </div>
                    
                    <!-- 指标说明 -->
                    <div style="background:#f8fafc;border-radius:10px;padding:14px;margin-bottom:16px;border:1px solid #e2e8f0;">
                        <div style="font-weight:600;color:#475569;font-size:13px;margin-bottom:12px;">📖 指标计算说明</div>
                        <div style="display:grid;gap:10px;font-size:12px;line-height:1.6;">
                            <div>
                                <span style="font-weight:600;color:#0369a1;">引用率 = 品牌提及次数 ÷ 总查询数 × 100%</span>
                                <div style="color:#64748b;margin-top:2px;">该平台搜索结果中，包含"松江招聘"相关内容的比例。引用率越高，说明该平台对您的内容收录越好。</div>
                            </div>
                            <div>
                                <span style="font-weight:600;color:#0369a1;">品牌提及次数 = ${m.brand_mention_count}</span>
                                <div style="color:#64748b;margin-top:2px;">在 ${m.total_queries} 次搜索中，提及"松江"相关信息的网页/内容数量。这些内容被 AI 搜索系统索引，可能在用户查询时作为参考来源。</div>
                            </div>
                            <div>
                                <span style="font-weight:600;color:#0369a1;">被引用的是什么？</span>
                                <div style="color:#64748b;margin-top:2px;">被引用的是您的"松江招聘"岗位信息网页。当用户在 ${name} 搜索相关关键词时，AI 可能参考这些网页的内容来生成回答。</div>
                            </div>
                            <div>
                                <span style="font-weight:600;color:#0369a1;">谁在引用？</span>
                                <div style="color:#64748b;margin-top:2px;">${name}（${platform.toUpperCase()}）是 AI 搜索引擎。它会将您的内容作为知识来源，在回答用户问题时引用。</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 健康状态解读 -->
                    <div style="background:#fef3c7;border-radius:10px;padding:14px;margin-bottom:16px;">
                        <div style="display:flex;align-items:flex-start;gap:10px;">
                            <span style="font-size:20px;">💡</span>
                            <div>
                                <div style="font-weight:600;color:#92400e;font-size:13px;">${healthTip}</div>
                                <div style="font-size:12px;color:#a16207;margin-top:4px;">${healthLabel === '✅ 健康' ? '当前引用率≥1%，表示该平台对您的松江招聘内容有良好引用' : healthLabel === '⚠️ 需关注' ? '建议优化岗位描述，增加 GEO 合规内容以提升引用率' : '建议检查内容是否成功分发，或联系平台确认收录情况'}</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 详细数据 -->
                    <h4 style="margin:0 0 12px;font-size:14px;font-weight:600;">📊 详细指标</h4>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
                        <div style="background:var(--gray-50);border-radius:8px;padding:14px;">
                            <div style="font-size:11px;color:var(--text-muted);">总查询数</div>
                            <div style="font-size:20px;font-weight:600;margin-top:4px;">${m.total_queries}</div>
                            <div style="font-size:10px;color:#94a3b8;margin-top:4px;">检测时搜索的网页总数</div>
                        </div>
                        <div style="background:var(--gray-50);border-radius:8px;padding:14px;">
                            <div style="font-size:11px;color:var(--text-muted);">趋势</div>
                            <div style="font-size:16px;font-weight:600;margin-top:4px;color:${m.trend==='rising'?'#059669':m.trend==='falling'?'#dc2626':'var(--text)'}">${trendLabels[m.trend]||'未知'}</div>
                            <div style="font-size:10px;color:#94a3b8;margin-top:4px;">近7天引用率变化</div>
                        </div>
                        <div style="background:var(--gray-50);border-radius:8px;padding:14px;">
                            <div style="font-size:11px;color:var(--text-muted);">告警阈值</div>
                            <div style="font-size:20px;font-weight:600;margin-top:4px;">0.5%</div>
                            <div style="font-size:10px;color:#94a3b8;margin-top:4px;">低于此值触发告警</div>
                        </div>
                        <div style="background:var(--gray-50);border-radius:8px;padding:14px;">
                            <div style="font-size:11px;color:var(--text-muted);">最后检测</div>
                            <div style="font-size:14px;font-weight:600;margin-top:4px;">${m.last_check_time?m.last_check_time.slice(0,16).replace('T',' '):'-'}</div>
                            <div style="font-size:10px;color:#94a3b8;margin-top:4px;">最近一次检测时间</div>
                        </div>
                    </div>
                    
                    <!-- 查询说明 -->
                    <div style="background:#fff7ed;border-radius:8px;padding:12px;margin-bottom:16px;font-size:11px;color:#9a3412;line-height:1.5;">
                        <div style="font-weight:600;margin-bottom:4px;">🔍 本次检测查询了这些内容：</div>
                        <div style="margin-left:12px;">搜索关键词：<strong>"松江招聘"、"松江找工作"、"松江求职"</strong> 等相关词</div>
                        <div style="margin-left:12px;">检测范围：该平台搜索结果中包含松江招聘信息的网页</div>
                    </div>
                    
                    <!-- 趋势解读 -->
                    <div style="background:#f0fdf4;border-radius:10px;padding:14px;margin-bottom:16px;">
                        <div style="display:flex;align-items:flex-start;gap:10px;">
                            <span style="font-size:20px;">${m.trend==='rising'?'📈':m.trend==='falling'?'📉':'➡️'}</span>
                            <div>
                                <div style="font-weight:600;color:#166534;font-size:13px;">趋势解读: ${trendLabels[m.trend]||'未知'}</div>
                                <div style="font-size:12px;color:#15803d;margin-top:4px;">${trendTips[m.trend]||trendTips.unknown}</div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 建议 -->
                    <h4 style="margin:0 0 12px;font-size:14px;font-weight:600;">💡 优化建议</h4>
                    <div style="background:var(--gray-50);border-radius:10px;padding:14px;font-size:13px;line-height:1.7;">
                        ${pct>=1?`<p style="margin:0 0 8px;">✅ 继续保持！建议定期更新岗位内容，保持引用率稳定。</p>`:''}
                        ${pct>=0.5&&pct<1?`<p style="margin:0 0 8px;">📝 建议优化方向：</p><ul style="margin:0;padding-left:20px;"><li>增强岗位描述的 GEO 合规性</li><li>增加关键词密度和自然度</li><li>确保 Schema 结构化数据完整</li></ul>`:''}
                        ${pct<0.5?`<p style="margin:0 0 8px;">🚨 急需优化：</p><ul style="margin:0;padding-left:20px;"><li>检查内容是否成功分发到该平台</li><li>重新生成并推送岗位数据</li><li>提升内容质量和 GEO 合规性</li><li>考虑联系平台确认收录状态</li></ul>`:''}
                    </div>
                    
                    <!-- 引用详情（关键词、来源、场景） -->
                    <h4 style="margin:16px 0 12px;font-size:14px;font-weight:600;">🔗 引用详情</h4>
                    <div style="background:#f0fdf4;border-radius:10px;padding:14px;font-size:13px;">
                        <!-- 被引用的关键词 -->
                        <div style="margin-bottom:14px;">
                            <div style="font-weight:600;color:#166534;margin-bottom:8px;">📌 被引用的关键词</div>
                            <div style="display:flex;flex-wrap:wrap;gap:6px;">
                                ${(m.cited_keywords||[]).map(kw=>`<span style="background:#dcfce7;color:#166534;padding:3px 10px;border-radius:12px;font-size:11px;">${esc(kw)}</span>`).join('')}
                                ${!(m.cited_keywords&&m.cited_keywords.length)?'<span style="color:#94a3b8;font-size:12px;">暂无数据</span>':''}
                            </div>
                            <div style="margin-top:8px;font-size:11px;color:#64748b;">这些是触发引用的搜索关键词，AI 在搜索这些词时参考了您的内容</div>
                        </div>
                        
                        <!-- 被引用的来源 -->
                        <div style="margin-bottom:14px;">
                            <div style="font-weight:600;color:#166534;margin-bottom:8px;">📄 被引用的来源</div>
                            <div style="display:grid;gap:8px;">
                                ${(m.cited_sources||[]).map(src=>`
                                    <div style="background:white;border-radius:8px;padding:10px;border:1px solid #bbf7d0;">
                                        <div style="font-weight:600;color:#1e293b;font-size:12px;">${esc(src.title||'松江招聘岗位')}</div>
                                        <a href="${esc(src.url||'#')}" target="_blank" style="color:#2563eb;font-size:11px;word-break:break-all;">${esc(src.url||'').slice(0,60)}${src.url&&src.url.length>60?'...':''}</a>
                                        ${src.snippet?`<div style="margin-top:4px;font-size:11px;color:#64748b;">${esc(src.snippet)}</div>`:''}
                                        ${src.relevance_score?`<div style="margin-top:4px;"><span class="tag tag-green" style="font-size:10px;">相关度 ${(src.relevance_score*100).toFixed(0)}%</span></div>`:''}
                                    </div>
                                `).join('')}
                                ${!(m.cited_sources&&m.cited_sources.length)?'<span style="color:#94a3b8;font-size:12px;">暂无引用来源数据</span>':''}
                            </div>
                        </div>
                        
                        <!-- 引用场景 -->
                        ${(m.citation_contexts||[]).length>0?`
                        <div>
                            <div style="font-weight:600;color:#166534;margin-bottom:8px;">💬 引用场景</div>
                            ${(m.citation_contexts||[]).map(ctx=>`
                                <div style="background:white;border-radius:8px;padding:12px;margin-bottom:8px;border:1px solid #bbf7d0;">
                                    <div style="margin-bottom:6px;">
                                        <span style="background:#e0f2fe;color:#0369a1;padding:2px 8px;border-radius:4px;font-size:11px;">搜索词</span>
                                        <span style="margin-left:6px;font-weight:600;color:#1e293b;">"${esc(ctx.query||'')}"</span>
                                    </div>
                                    ${ctx.response_snippet?`<div style="font-size:12px;color:#475569;line-height:1.5;padding:8px;background:#f8fafc;border-radius:6px;">${esc(ctx.response_snippet)}</div>`:''}
                                    ${ctx.ai_platform?`<div style="margin-top:6px;font-size:11px;color:#64748b;">AI 平台：${esc(ctx.ai_platform)}</div>`:''}
                                    ${ctx.cited_urls&&ctx.cited_urls.length>0?`<div style="margin-top:4px;font-size:11px;color:#64748b;">引用链接：${ctx.cited_urls.map(u=>`<a href="${esc(u)}" target="_blank" style="color:#2563eb;">链接</a>`).join(', ')}</div>`:''}
                                </div>
                            `).join('')}
                        </div>`:''}
                    </div>
                </div>
                
                <!-- 底部操作 -->
                <div style="padding:16px 24px;border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end;">
                    <button onclick="Monitor.closeModal()" style="padding:10px 20px;border-radius:8px;border:1px solid var(--border);background:white;cursor:pointer;font-size:13px;">关闭</button>
                    <button onclick="Monitor.checkSinglePlatform('${esc(platform)}')" style="padding:10px 20px;border-radius:8px;border:none;background:#2563eb;color:white;cursor:pointer;font-size:13px;font-weight:500;">🔍 重新检测此平台</button>
                </div>
            </div>
        </div>`;

        // 创建弹窗
        const modal=document.createElement('div');
        modal.id='platformDetailModal';
        modal.innerHTML=html;
        document.body.appendChild(modal);
    },

    /** 关闭弹窗 */
    closeModal(e){
        if(e && e.target!==e.currentTarget) return;
        const m=document.getElementById('platformDetailModal');
        if(m) m.remove();
    },

    /** 单平台检测 */
    async checkSinglePlatform(platform){
        this.closeModal();
        toast(`正在检测 ${platform}...`, 'info');
        try{
            await API.get(`/api/monitor/citation?platform=${platform}`);
            toast(`✅ ${platform} 检测完成`, 'success');
            await this.load();
        }catch(e){
            toast('检测失败: '+e.message, 'error');
        }
    },

    /* ===== 保留原有基础统计渲染逻辑 ===== */

    _renderBasicStats(sr, str){
        const s=(sr&&sr.status==='fulfilled'?sr.data:{})?.data||str?.data||{};
        const sys=s.system||{};const db=s.database||{};
        const exec=s.execution||{}; // 历史记录由 _renderHistory 单独处理

        // 骨架屏切换：隐藏骨架，显示真实容器
        this._switchToReal('monitorCards', 'monitorCardsSkeleton');

        // 业务指标卡片
        document.getElementById('monitorCards').innerHTML=[
            { icon:'💼', title:'活跃岗位', value:s.total_active||0, sub:'待处理岗位数' },
            { icon:'🔥', title:'急招岗位', value:s.urgent_count||0, sub:'优先推送AI' },
            { icon:'✅', title:'合规通过率', value:`${exec.success_rate||0}%`, sub:`${exec.total_executions||0}次执行` },
        ].map(c=>`
            <div class="phase-card">
                <div class="phase-icon">${c.icon}</div>
                <div class="phase-title">${c.title}</div>
                <div style="font-size:22px;font-weight:700;margin:6px 0 2px;">${c.value}</div>
                <div style="font-size:11px;color:var(--text-muted);">${c.sub}</div>
            </div>
        `).join('');

        // 分类分布图 [M-05] 使用增强版条形图
        const cats=s.categories||{};const maxC=Math.max(...Object.values(cats),1);
        const catContainer=document.getElementById('chartCategory');
        catContainer.innerHTML=Object.keys(cats).length?
            Object.entries(cats).map(([k,v])=>this._renderEnhancedBar('chartCategory',k,v,maxC,'#2563eb,#7c3aed')).join('')
            :'<p style="color:var(--text-muted);padding:20px 0;">暂无数据</p>';

        // 薪资分布 [M-05] 使用增强版条形图
        const sal=s.salary_ranges||{};const maxS=Math.max(...Object.values(sal),1);
        document.getElementById('chartSalary').innerHTML=Object.keys(sal).length?
            Object.entries(sal).map(([k,v])=>this._renderEnhancedBar('chartSalary',k,v,maxS,'#059669,#10b981','元')).join('')
            :'<p style="color:var(--text-muted);padding:20px 0;">暂无数据</p>';

        // 系统状态表
        const tb=document.getElementById('sysStatusTable');
        tb.innerHTML=[
            ['版本',sys.version||'-'],['Python',`v${sys.python_version}`],['平台',sys.platform||'-'],
            ['数据库',db.connected?`${db.database} (${db.version})`:'未连接',db.available?'可配置':'驱动未安装'],
            ['数据表',db.tables?.join(', ')||'-','-'],
        ].map(r=>`<tr><td>${r[0]}</td><td style="font-weight:500">${r[1]}</td><td style="color:var(--text-muted)">${r[2]}</td></tr>`).join('');
    },

    /** 渲染执行历史 (增强版 - 支持筛选) */
    _renderHistory(data){
        const hist=data.history||[];
        let filtered=hist;
        const modeFilter=document.getElementById('historyModeFilter')?.value;
        if(modeFilter)filtered=hist.filter(h=>h.mode===modeFilter);

        const listEl=document.getElementById('historyList');
        // emptyEl 由 toggleEl('historyEmpty') 内部查找，此处保留引用以备扩展
        if(filtered.length===0){
            // 骨架屏切换
            this._switchToReal('historyList', 'historyListSkeleton');
            listEl.innerHTML='';
            toggleEl('historyEmpty',true);
            return;
        }
        
        // 骨架屏切换：隐藏骨架，显示真实容器
        this._switchToReal('historyList', 'historyListSkeleton');
        toggleEl('historyEmpty',false);

        const labels={pipeline:'Pipeline',db:'Database',import:'Import'};
        listEl.innerHTML=filtered.map(h=>{
            const res=h.result||{};const ok=res.status==='success'||res.status==='dry_run';
            return `
            <div class="phase-card" style="margin-bottom:10px;padding:14px;">
                <div style="display:flex;align-items:center;gap:12px;">
                    <span style="font-size:22px">${ok?'✅':'❌'}</span>
                    <div style="flex:1;">
                        <div style="font-weight:600">${labels[h.mode]||h.mode} 模式</div>
                        <div style="font-size:12px;color:var(--text-muted)">
                            ${h.timestamp?.replace('T',' ')?.slice(0,19)} · 耗时 ${res.duration||'?'}s
                        </div>
                    </div>
                    <span class="tag ${ok?'tag-green':'tag-red'}">${res.status||'?'}</span>
                </div>
                <details style="margin-top:8px;">
                    <summary style="cursor:pointer;color:var(--primary);font-size:12px;padding:2px 0;">展开详情</summary>
                    <pre style="background:var(--gray-50);padding:10px;border-radius:6px;font-size:11px;margin-top:6px;overflow:auto;max-height:180px;white-space:pre-wrap;">${JSON.stringify(res,null,2)}</pre>
                </details>
            </div>`}).join('');
    },

    /** 执行历史筛选 (F7) */
    filterHistory(){this.load();},

    // [L-02] 自动刷新机制
    _startAutoRefresh(){
        this._stopAutoRefresh();
        this._autoRefreshTimer = setInterval(()=>{
            if(document.visibilityState==='visible' && !document.querySelector('#page-monitor.hidden')){
                this.load();
            }
        }, 30000); // 30秒自动刷新
    },
    _stopAutoRefresh(){
        if(this._autoRefreshTimer){clearInterval(this._autoRefreshTimer); this._autoRefreshTimer=null;}
    }

};


// ============================================================
//  PAGE 5: CONFIG（动态配置系统）
// ============================================================
var Config = window.Config = {
    _schema: null,          // 完整配置 schema
    _groups: null,          // 分组列表
    _currentGroup: 'SITE',   // 当前激活的分组
    _modifiedKeys: new Set(), // 已修改但未保存的 key 集合

    /** 加载配置 schema + 渲染界面 */
    async load() {
        try {
            const cr = await API.get('/api/config');
            const data = (cr && typeof cr.data === 'object') ? cr.data : {};

            // 兼容旧 API 返回格式（无 schema 时降级）
            if (!data.schema || !Array.isArray(data.schema)) {
                this._renderFallback(data);
                return;
            }

            this._schema = data.schema;
            this._groups = Array.isArray(data.groups) ? data.groups : [];

            // 渲染左侧分组导航
            this._renderGroupNav();

            // 默认选中第一个分组
            if (this._groups.length > 0) {
                this.switchGroup(this._groups[0].id);
            }
        } catch (e) {
            console.warn('[Config] load error:', e);
            document.getElementById('configFormArea').innerHTML =
                '<p style="color:var(--text-muted);text-align:center;padding:40px 0;">加载配置失败，请刷新重试</p>';
        }
    },

    /** 切换配置分组 */
    switchGroup(groupId) {
        this._currentGroup = groupId;

        // 更新导航高亮
        document.querySelectorAll('.cfg-nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.group === groupId);
        });

        // 渲染表单
        this._renderForm(groupId);
    },

    /** 渲染左侧分组导航 */
    _renderGroupNav() {
        const navEl = document.getElementById('configGroupNav');
        if (!navEl || !this._groups.length) return;

        navEl.innerHTML = this._groups.map(g =>
            `<div class="cfg-nav-item ${g.id === this._currentGroup ? 'active' : ''}"
                 data-group="${g.id}" onclick="Config.switchGroup('${g.id}')">
                <span class="cfg-nav-label">${g.label}</span>
             </div>`
        ).join('');
    },

    /** 渲染指定分组的配置表单 */
    _renderForm(groupId) {
        const formArea = document.getElementById('configFormArea');
        if (!formArea) return;

        const fields = (this._schema || []).filter(f => f && f.group === groupId);
        if (!fields.length) {
            formArea.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px 0;">该分组暂无可配置项</p>';
            return;
        }

        let html = '';

        // 按字段 order 排序
        const sorted = [...fields].sort((a, b) => (a.order || 99) - (b.order || 99));

        for (const f of sorted) {
            html += this._renderField(f);
        }

        formArea.innerHTML = html;

        // 绑定 change 事件追踪修改
        formArea.querySelectorAll('[data-config-key]').forEach(input => {
            input.addEventListener('change', e => this._onFieldChange(e));
            input.addEventListener('input', e => {
                // 对文本输入实时标记修改状态
                if (e.target.tagName === 'INPUT' && e.target.type !== 'checkbox') {
                    this._onFieldChange(e);
                }
            });
        });

        // 渲染底部操作按钮
        this._renderActions();
    },

    /** 渲染单个配置字段 */
    _renderField(f) {
        const key = f.key || '';
        const label = f.label || key;
        const desc = f.description || '';
        const val = f.current_value !== undefined ? f.current_value : (f.default !== undefined ? f.default : '');
        const placeholder = f.placeholder || '';
        const isSecret = !!f.is_secret;
        const requiresRestart = !!f.requires_restart;
        const inputId = 'cf-' + key;

        let controlHtml = '';
        const type_ = (f.type || 'STRING').toUpperCase(); // 后端用 type，前端读取 type

        switch (type_) {
            case 'PASSWORD':
                controlHtml = `<div style="position:relative;">
                    <input id="${inputId}" type="password" data-config-key="${key}"
                           value="${this._escAttr(val)}" placeholder="${this._escAttr(placeholder)}"
                           class="input cfg-input">
                    <button type="button" class="cfg-pw-toggle" onclick="Config._togglePw('${inputId}')" title="显示/隐藏">👁</button>
                </div>`;
                break;

            case 'NUMBER':
                const minVal = f.validation?.min !== undefined ? f.validation.min : '';
                const maxVal = f.validation?.max !== undefined ? f.validation.max : '';
                controlHtml = `<input id="${inputId}" type="number" data-config-key="${key}"
                       value="${val}" min="${minVal}" max="${maxVal}"
                       placeholder="${this._escAttr(placeholder)}" class="input cfg-input" style="max-width:200px;">`;
                break;

            case 'TOGGLE':
                const checked = val === true || val === 1 || val === 'true' || val === 'on' ? 'checked' : '';
                controlHtml = `<label class="cfg-toggle-wrap">
                    <input id="${inputId}" type="checkbox" data-config-key="${key}" ${checked}
                           class="cfg-toggle">
                    <span class="cfg-toggle-slider"></span>
                    <span style="margin-left:8px;font-size:13px;color:var(--text-secondary);">
                        ${checked ? '已启用' : '已禁用'}
                    </span>
                </label>`;
                break;

            case 'SELECT':
                const options = Array.isArray(f.options) ? f.options : [];
                const optsHtml = options.map(o => {
                    const optVal = (typeof o === 'object' && o !== null) ? (o.value || '') : o;
                    const optLabel = (typeof o === 'object' && o !== null) ? (o.label || optVal) : o;
                    return `<option value="${this._escAttr(optVal)}">${optLabel}</option>`;
                }).join('');
                controlHtml = `<select id="${inputId}" data-config-key="${key}" class="select cfg-input" style="max-width:280px;">${optsHtml}</select>`;
                break;

            case 'TEXTAREA':
                controlHtml = `<textarea id="${inputId}" data-config-key="${key}"
                        placeholder="${this._escAttr(placeholder)}"
                        class="textarea cfg-input" rows="4" style="min-height:80px;">${this._escAttr(val)}</textarea>`;
                break;

            case 'PATH':
                controlHtml = `<div style="display:flex;gap:8px;align-items:center;">
                    <input id="${inputId}" type="text" data-config-key="${key}"
                           value="${this._escAttr(val)}" placeholder="${this._escAttr(placeholder)}"
                           class="input cfg-input" readonly style="background:var(--gray-50);">
                    <button type="button" class="btn-outline btn-sm" onclick="Config._pickPath('${inputId}')" style="flex-shrink:0;">浏览...</button>
                </div>`;
                break;

            case 'ACTION':
                // 特殊处理：操作按钮类型（如清理数据）
                const btnLabel = f.label || '执行操作';
                const btnStyle = key.includes('clear') || key.includes('delete') || key.includes('danger')
                    ? 'btn-danger btn-sm'
                    : 'btn-primary btn-sm';
                controlHtml = `<div style="display:flex;align-items:center;gap:12px;">
                    <button type="button" class="${btnStyle}" 
                            onclick="Config.executeAction('${key}', this)">
                        ${btnLabel}
                    </button>
                    <span id="action-status-${key.replace(/\./g, '_')}" style="font-size:12px;color:var(--text-muted);"></span>
                </div>`;
                break;

            default: // STRING
                controlHtml = `<input id="${inputId}" type="text" data-config-key="${key}"
                       value="${this._escAttr(val)}" placeholder="${this._escAttr(placeholder)}"
                       class="input cfg-input">`;
                break;
        }

        // 字段级提示标签
        const badges = [];
        if (isSecret) badges.push('<span class="badge badge-orange" style="font-size:10px;">敏感信息</span>');
        if (requiresRestart) badges.push('<span class="badge badge-blue" style="font-size:10px;">需重启</span>');

        return `<div class="cfg-field" data-field-key="${key}">
            <label class="form-label cfg-label" for="${inputId}">
                ${label}
                ${badges.length > 0 ? '<span style="display:inline-flex;gap:6px;margin-left:8px;">' + badges.join('') + '</span>' : ''}
            </label>
            ${desc ? `<p class="cfg-desc">${desc}</p>` : ''}
            ${controlHtml}
        </div>`;
    },

    /** 渲染底部操作按钮 */
    _renderActions() {
        const actionsEl = document.getElementById('configActions');
        if (!actionsEl) return;

        actionsEl.innerHTML = `
            <button class="btn-primary" onclick="Config.saveAll()" id="cfgSaveBtn">
                💾 保存所有更改
            </button>
            <button class="btn-outline" onclick="Config.resetGroup()" id="cfgResetBtn">
                ↩️ 重置当前分组
            </button>
            <span id="cfgModifiedHint" style="font-size:12px;color:var(--text-muted);display:none;">
                有 ${this._modifiedKeys.size} 项未保存修改
            </span>
        `;
    },

    /** 字段值变更事件 */
    _onFieldChange(e) {
        const key = e.target.dataset.configKey;
        if (!key) return;
        this._modifiedKeys.add(key);

        // 标记字段视觉变化
        const fieldEl = e.target.closest('.cfg-field');
        if (fieldEl) fieldEl.classList.add('modified');

        // Toggle 类型实时更新标签文字
        if (e.target.classList.contains('cfg-toggle')) {
            const label = fieldEl.querySelector('.cfg-toggle-wrap span:last-child');
            if (label) label.textContent = e.target.checked ? '已启用' : '已禁用';
        }

        // 更新未保存计数
        const hint = document.getElementById('cfgModifiedHint');
        if (hint) {
            hint.style.display = this._modifiedKeys.size > 0 ? '' : 'none';
            hint.textContent = `有 ${this._modifiedKeys.size} 项未保存修改`;
        }
    },

    /** 批量保存所有修改 */
    async saveAll() {
        if (this._modifiedKeys.size === 0) {
            toast('没有需要保存的修改', 'info');
            return;
        }

        const btn = document.getElementById('cfgSaveBtn');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ 保存中...'; }

        // 收集所有修改的字段值
        const updates = {};
        for (const key of this._modifiedKeys) {
            const input = document.querySelector(`[data-config-key="${key}"]`);
            if (!input) continue;

            const fieldDef = (this._schema || []).find(f => f.key === key);
            const fieldType = (fieldDef && fieldDef.type_) ? fieldDef.type_.toUpperCase() : 'STRING';

            if (fieldType === 'TOGGLE') {
                updates[key] = input.checked;
            } else if (fieldType === 'NUMBER') {
                updates[key] = input.value !== '' ? Number(input.value) : '';
            } else {
                updates[key] = input.value;
            }
        }

        try {
            const res = await API.put('/api/config', updates);
            const resultData = res && res.data ? res.data : {};

            if (resultData.success || resultData.updated_count > 0) {
                toast(`成功保存 ${resultData.updated_count || this._modifiedKeys.size} 项配置`, 'success');

                // 清除修改标记
                this._modifiedKeys.clear();
                document.querySelectorAll('.cfg-field.modified').forEach(el => el.classList.remove('modified'));

                const hint = document.getElementById('cfgModifiedHint');
                if (hint) hint.style.display = 'none';

                // 显示是否需要重启
                const statusEl = document.getElementById('cfgStatus');
                if (statusEl && resultData.requires_restart) {
                    statusEl.innerHTML =
                        '<p style="color:var(--warning);font-size:13px;display:flex;align-items:center;gap:6px;">⚠️ 部分配置需要重启服务后生效</p>';
                } else if (statusEl) {
                    statusEl.innerHTML = '';
                }

                // 重新加载当前分组以获取最新值
                this._renderForm(this._currentGroup);
            } else {
                throw new Error(resultData.message || '保存失败');
            }
        } catch (err) {
            console.error('[Config] save error:', err);
            toast('保存失败: ' + (err.message || '未知错误'), 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '💾 保存所有更改'; }
        }
    },

    /** 重置当前分组所有字段到当前存储值 */
    resetGroup() {
        if (this._modifiedKeys.size === 0) {
            toast('没有需要重置的修改', 'info');
            return;
        }
        this._modifiedKeys.clear();
        this._renderForm(this._currentGroup);

        const hint = document.getElementById('cfgModifiedHint');
        if (hint) hint.style.display = 'none';
        const statusEl = document.getElementById('cfgStatus');
        if (statusEl) statusEl.innerHTML = '';
        toast('已重置当前分组', 'success');
    },

    /** 切换密码显示/隐藏 */
    _togglePw(inputId) {
        const el = document.getElementById(inputId);
        if (!el) return;
        el.type = el.type === 'password' ? 'text' : 'password';
    },

    /** 旧版 API 降级渲染 */
    _renderFallback(data) {
        const fmt = items => (Array.isArray(items) ? items : []).map(([k, v]) =>
            `<div style="display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--border);font-size:13px;">
                <span style="color:var(--text-secondary)">${k}</span><span style="font-weight:500">${v}</span>
            </div>`
        ).join('');

        const area = document.getElementById('configFormArea');
        const actions = document.getElementById('configActions');
        if (area) {
            area.innerHTML = `
                <h3 style="margin-bottom:16px;">🗄️ 数据库</h3>${fmt([
                    ['Host', data.database?.host || '未配置'],
                    ['数据库', data.database?.database || '未配置'],
                    ['SSL', data.database?.ssl_enabled ? '启用' : '禁用']
                ])}
                <h3 style="margin:24px 0 16px;">🔑 平台凭证</h3>${fmt([
                    ['微信', data.wechat?.configured ? '✅ 已配置' : '❌ 未配置'],
                    ['抖音/豆包', data.douyin?.configured ? '✅ 已配置' : '❌ 未配置'],
                    ['百度文心', data.baidu?.configured ? '✅ 已配置' : '❌ 未配置']
                ])}
                <h3 style="margin:24px 0 16px;">📡 监控告警</h3>${fmt([
                    ['监控开关', data.monitoring?.enabled ? '开启' : '关闭'],
                    ['引用率阈值', `${data.monitoring?.threshold || 0.5}%`]
                ])}
            `;
        }
        if (actions) actions.innerHTML = '';
    },

    /** HTML 属性转义 */
    _escAttr(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                         .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    /** [C2] 导出配置 */
    async exportConfig(){
        try{
            // 创建下载链接
            const a = document.createElement('a');
            a.href = '/api/config/export?format=json';
            a.download = '';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            toast('配置导出已开始下载','success');
        }catch(e){
            toast('导出失败: '+e.message,'error');
        }
    },

    /** [C2] 导入配置 (仅支持 JSON 格式) */
    async importConfig(event){
        const file = event.target.files[0];
        if(!file) return;

        // [M-04 fix] 仅接受 JSON 文件，非 JSON 直接提示
        if(!file.name.endsWith('.json')){
            toast(`不支持的文件格式 "${file.name.split('.').pop()}"，仅支持 .json 配置文件`,'warning');
            event.target.value = '';
            return;
        }

        try{
            const text = await file.text();
            const configData = JSON.parse(text);

            const r = await API.post('/api/config/import', {config: configData, merge_mode:'merge'});
            const d = r.data||{};

            if(d.success || d.imported_count > 0){
                toast(`成功导入 ${d.imported_count} 项配置`,'success');
                this.load(); // 刷新界面
            } else {
                toast(d.error || '导入失败','error');
            }

            // 重置 input
            event.target.value = '';

        }catch(e){
            toast('导入失败: '+e.message,'error');
            event.target.value = '';
        }
    },

    /** [危险] 一键清理所有业务数据 */
    async clearBusinessData(e){
        // 二次确认
        if(!confirm('⚠️ 确认要清理所有业务数据吗？\n\n此操作将删除：\n• 所有岗位数据\n• uploads/ 目录文件\n• audit_logs/ 审计记录\n• dist/ 分发结果\n\n⚠️ 此操作不可逆！\n\n建议：操作前先导出配置备份')){
            return;
        }
        
        // 三次确认（输入确认词）
        const confirmPhrase = prompt('请输入 "确认清理" 以继续：');
        if(confirmPhrase !== '确认清理'){
            toast('已取消清理操作', 'info');
            return;
        }

        const btn = e?.target || document.querySelector('[onclick*="clearBusinessData"]');
        if(btn){ btn.disabled = true; btn.textContent = '⏳ 清理中...'; }

        try{
            const r = await API.post('/api/data/cleanup', {});
            const d = r.data || {};

            if(d.success){
                const msg = `✅ 清理完成！共删除 ${d.deleted_jobs || 0} 条岗位，清理了 ${d.deleted_files || 0} 个文件`;
                toast(msg, 'success');
                
                // 刷新岗位列表（如果有的话）
                if(typeof Jobs !== 'undefined' && Jobs.load){
                    setTimeout(() => Jobs.load(1), 500);
                }
            } else {
                throw new Error(d.error || '清理失败');
            }
        }catch(e){
            toast('清理失败: ' + (e.message || '未知错误'), 'error');
        }finally{
            if(btn){ btn.disabled = false; btn.textContent = '🗑️ 清理业务数据'; }
        }
    },

    /** 执行配置操作按钮 */
    async executeAction(key, btn){
        if(key === 'advanced.clear_business_data'){
            await this.clearBusinessData({ target: btn });
            return;
        }
        
        // 其他操作可在此扩展
        toast('未知操作: ' + key, 'warning');
    },

    /** [L-05] PATH 字段文件选择 — 使用原生 file input 选择路径 */
    _pickPath(inputId) {
        const input = document.createElement('input');
        input.type = 'file';
        input.style.display = 'none';
        input.onchange = () => {
            if(input.files.length > 0) {
                // 使用文件名作为路径（Web 环境无法获取完整绝对路径，使用 File API 兼容方案）
                const target = document.getElementById(inputId);
                if(target) {
                    // 存储文件对象供后续上传使用
                    target._selectedFile = input.files[0];
                    target.value = input.files[0].name;
                }
            }
            input.remove();
        };
        document.body.appendChild(input);
        input.click();
    }
};


// ============================================================
//  PAGE 6: GEO 四阶段框架概览
// ============================================================
const GEOFramework = {
    async load(){
        try{
            const r=await API.get('/api/geo/framework');
            const fw=r.data||{};
            const layers=fw.layers||[];
            const geoVsSeo=fw.geo_vs_seo||{};
            const roadmap=fw.roadmap||{};

            // 四阶段卡片
            const icons={existence:'🏗️',recommendation:'⭐',conversion:'🎯',brand:'👑'};
            const colors={existence:'#1a73e8',recommendation:'#7c3aed',conversion:'#059669',brand:'#d97706'};
            
            document.getElementById('geoFrameworkCards').innerHTML=layers.map(l=>`
                <div class="phase-card" style="border-left:4px solid ${esc(colors[l.id])||'#ccc'};padding-left:16px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                        <span style="font-size:24px">${icons[l.id]||'📋'}</span>
                        <div>
                            <div style="font-weight:700;font-size:16px;">Phase ${esc(l.phase)}: ${esc(l.name)}</div>
                            <div style="font-size:12px;color:var(--text-muted);">${esc(l.chinese_alias)}</div>
                        </div>
                        <span class="tag ${l.status==='implemented'?'tag-green':l.status==='partial'?'tag-blue':'tag-gray'}" style="margin-left:auto;">
                            ${l.status==='implemented'?'已实现':l.status==='partial'?'部分':'规划中'}
                        </span>
                    </div>
                    <div style="background:rgba(0,0,0,0.03);padding:10px;border-radius:8px;margin-bottom:10px;">
                        <div style="font-weight:600;color:var(--danger);margin-bottom:6px;">${esc(l.core_question)}</div>
                        <p style="font-size:13px;color:var(--text-secondary);line-height:1.5;">${esc(l.goal)}</p>
                    </div>
                    <details style="font-size:13px;">
                        <summary style="cursor:pointer;color:var(--primary);">落地动作 (${(l.actions||[]).length}项)</summary>
                        <ul style="margin-top:6px;padding-left:20px;line-height:1.7;">
                        ${(l.actions||[]).map(a=>`<li>${esc(a)}</li>`).join('')}
                        </ul>
                    </details>
                </div>
            `).join('');

            // GEO vs SEO 对比表
            const seoKeys=['core_logic','goal','strategy','persistence'];
            const seoLabels={'core_logic':'核心逻辑','goal':'目标','strategy':'策略','persistence':'持久性'};
            document.getElementById('geoVsSeoBody').innerHTML=seoKeys.map(k=>`
                <tr><td style="font-weight:500;background:var(--gray-50);">${esc(seoLabels[k])}</td>
                    <td style="color:#dc2626;">${esc(geoVsSeo.traditional_seo?.[k])||'-'}</td>
                    <td style="color:#059669;font-weight:500;">${esc(geoVsSeo.geo?.[k])||'-'}</td></tr>
            `).join('');

            // 路线图 [M-06] 增加可视化进度标注
            const phaseStatusMap = {}; // 从 layers 收集 status
            layers.forEach(l => { phaseStatusMap[l.id] = l.status || 'planned'; });
            const statusStyle = {
                implemented: {bg:'#ecfdf5',border:'#a7f3d0',icon:'●',text:'已完成'},
                partial:     {bg:'#fffbeb',border:'#fde68a',icon:'◐',text:'进行中'},
                planned:     {bg:'#f9fafb',border:'#e5e7eb',icon:'○',text:'规划中'},
            };
            document.getElementById('geoRoadmap').innerHTML=Object.entries(roadmap).map(([k,v])=>{
                // 尝试从 key 匹配对应的阶段状态
                const phaseKey = k.toLowerCase().replace(/[ _]/g,'');
                let matchedStatus = 'planned';
                for(const [pk,ps] of Object.entries(phaseStatusMap)){
                    if(phaseKey.includes(pk.toLowerCase()) || pk.toLowerCase().includes(phaseKey)){
                        matchedStatus = ps; break;
                    }
                }
                const st = statusStyle[matchedStatus] || statusStyle.planned;
                return `
                <div style="display:flex;align-items:center;gap:12px;padding:12px 14px;margin-bottom:8px;border-radius:8px;border-left:4px solid ${st.border};background:${st.bg};">
                    <span style="min-width:90px;font-family:monospace;font-weight:700;color:var(--primary);font-size:13px;">${esc(k.replace('_',' '))}</span>
                    <span style="color:var(--text-muted);">→</span>
                    <span style="flex:1;font-size:13px;">${esc(v)}</span>
                    <span style="display:flex;align-items:center;gap:5px;font-size:11px;color:${st.border};font-weight:600;background:white;padding:4px 10px;border-radius:20px;border:1px solid ${st.border};white-space:nowrap;">
                        ${st.icon} ${st.text}
                    </span>
                </div>`;
            }).join('');

            // API 端点
            const allApis=[];
            layers.forEach(l=>{(l.api_endpoints||[]).forEach(ep=>allApis.push({layer:l.id,name:ep}));});
            document.getElementById('geoApiEndpoints').innerHTML=allApis.map(a=>`
                <div style="padding:8px 0;display:flex;align-items:center;gap:8px;border-bottom:1px solid var(--border);">
                    <code style="background:var(--gray-50);padding:3px 8px;border-radius:4px;font-size:11px;">${a.name}</code>
                    <span class="tag tag-sm" style="color:${colors[a.layer]}">${layers.find(l=>l.id===a.layer)?.name||''}</span>
                    <button class="btn-outline btn-sm" onclick="window.open('${a.name}','_blank')" style="margin-left:auto;padding:2px 10px;font-size:11px;">测试</button>
                </div>
            `).join('');
        }catch(e){toast('GEO框架加载失败:'+e.message,'error');}
    }
};


// ============================================================
//  PAGE 7: GEO 审计评分
// ============================================================
var GEOAudit = window.GEOAudit = {
    _lastAuditResult: null,  // [A1] 缓存最近一次审计结果
    _lastJobId: null,        // [A1] 最近审计的岗位ID
    _auditBusy: false,       // [防重复点击] 审计执行锁

    async init(){
        // 加载岗位列表到下拉选择框
        try{
            const r=await API.get('/api/jobs?per_page=200');
            const jobs=r.data?.data||[];
            const sel=document.getElementById('auditJobSelect');
            sel.innerHTML='<option value="">选择岗位进行审计...</option>'+
                jobs.map(j=>`<option value="${esc(j.id)}">${esc(j.title)} @ ${esc(j.company)}</option>`).join('');

            // [A1] 加载审计历史
            this._loadHistory();
        }catch(e){/* 静默失败 */}
    },

    async run(){
        if(this._auditBusy) return;
        this._auditBusy = true;

        const jobId=document.getElementById('auditJobSelect')?.value;
        const runBtn = document.querySelector('button[onclick="GEOAudit.run()"]');
        if(runBtn){runBtn.disabled=true;runBtn.textContent='⏳ 审计中...';}
        this._lastJobId = jobId || null;
        
        // 总分卡片 - 显示加载中
        document.getElementById('auditScoreCard').innerHTML=`
            <div class="phase-card"><div class="phase-icon">⏳</div><div>审计中...</div></div>`;
        document.getElementById('auditDimensionsLeft').innerHTML='';
        document.getElementById('auditDimensionsRight').innerHTML='';
        document.getElementById('auditSuggestionsArea').style.display='none';

        // 隐藏操作栏直到完成
        toggleEl('auditActionCard', false);

        try{
            let params=jobId?`?job_id=${jobId}`:'';
            const r=await API.get(`/api/geo/audit${params}`);
            const audit=r.data||{};
            
            this._lastAuditResult = audit;
            
            this._renderScoreCard(audit);
            this._renderDimensions(audit);
            this._renderSuggestions(audit);
            
            // 显示操作栏 + 启用按钮
            toggleEl('auditActionCard', true);
            document.getElementById('auditExportJsonBtn').disabled = false;
            document.getElementById('auditExportMdBtn').disabled = false;
            document.getElementById('auditSaveBtn').disabled = !jobId; // 无 job_id 不能保存
            
        }catch(e){
            toast('GEO审计失败:'+e.message,'error');
            document.getElementById('auditScoreCard').innerHTML=
                '<div class="phase-card" style="grid-column:1/-1;"><div class="phase-icon">❌</div><div>审计失败，请检查服务状态</div></div>';
        }
        finally{
            this._auditBusy = false;
            if(runBtn){runBtn.disabled=false;runBtn.textContent='▶ 执行审计';}
        }
    },

    /** [A2] 批量审计 — 带内嵌进度条 */
    async batchRun(){
        if(!confirm('批量审计将依次对所有(或所选分类)岗位执行GEO四阶段审计，可能需要较长时间。是否继续？')) return;

        toast('开始批量审计...','info');

        try{
            const jr = await API.get('/api/jobs?per_page=50');
            const jobs = jr.data?.data || [];

            if(jobs.length === 0) {
                toast('无岗位数据可审计','warning'); return;
            }

            let results = [];
            let passed = 0, failed = 0;

            // [L-03] 创建内嵌进度面板替代 alert
            const progEl = document.getElementById('auditBatchProgress');
            if(progEl){
                progEl.classList.remove('hidden');
                progEl.innerHTML = `
                    <div style="padding:16px;background:var(--bg-elevated);border-radius:10px;border:1px solid var(--border);">
                        <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                            <span style="font-size:13px;font-weight:600;">批量审计进度</span>
                            <span id="batchProgText" style="font-size:12px;color:var(--text-muted);">0/${jobs.length}</span>
                        </div>
                        <div style="height:8px;background:var(--gray-100);border-radius:4px;overflow:hidden;">
                            <div id="batchProgBar" style="height:100%;width:0%;background:linear-gradient(90deg,#2563eb,#7c3aed);border-radius:4px;transition:width 0.3s;"></div>
                        </div>
                        <div id="batchProgLog" style="margin-top:8px;font-size:11px;color:var(--text-muted);max-height:120px;overflow-y:auto;"></div>
                    </div>`;
            }

            for(let i = 0; i < jobs.length; i++){
                const j = jobs[i];
                try {
                    const ar = await API.get(`/api/geo/audit?job_id=${j.id}`);
                    const ad = ar.data || {};
                    results.push({
                        title: j.title,
                        company: j.company,
                        score: ad.total_score || 0,
                        grade: ad.grade || '?',
                        status: 'ok'
                    });
                    if(ad.total_score >= 60) passed++;
                    else failed++;
                } catch(e) {
                    results.push({title:j.title, company:j.company, score:0, grade:'?', status:'error'});
                    failed++;
                }

                // [L-03] 更新内嵌进度条
                const pct = Math.round((i+1)/jobs.length*100);
                const bar = document.getElementById('batchProgBar');
                const txt = document.getElementById('batchProgText');
                const log = document.getElementById('batchProgLog');
                if(bar) bar.style.width = pct+'%';
                if(txt) txt.textContent = `${i+1}/${jobs.length} (${pct}%)`;
                if(log) log.innerHTML += `<div>${esc(j.title)} → ${results[results.length-1].grade} (${results[results.length-1].score}分)</div>`;
            }

            // [L-03] 显示汇总结果（使用 toast + 控制台，不再使用原生 alert）
            const avgScore = results.length > 0 ? (results.reduce((s,r)=>s+r.score,0)/results.length).toFixed(1) : '0';
            toast(`批量审计完成！平均分 ${avgScore}/100 | 通过:${passed} | 需改进:${failed}`,'success');

            console.table(results);

            // 隐藏进度条
            setTimeout(()=>{if(progEl)progEl.classList.add('hidden');}, 3000);

        } catch(e) {
            toast('批量审计失败: '+e.message,'error');
        }
    },

    /** [A3] 导出审计结果 — 统一走后端 API */
    async exportResult(format){
        const jobId = this._lastJobId;
        // [L-04 fix] 统一走后端导出 API（后端格式化更完整）
        if(jobId){
            try{
                const a = document.createElement('a');
                a.href = `/api/geo/audit/export?job_id=${encodeURIComponent(jobId)}&format=${format}`;
                document.body.appendChild(a); a.click(); a.remove();
                toast(`已导出 ${format.toUpperCase()} 格式`,'success');
            }catch(e){toast('导出失败','error');}
        } else if(this._lastAuditResult){
            // 无 jobId 时从缓存生成前端报告（降级方案）
            this._downloadBlob(this._lastAuditResult, format);
        } else {
            toast('没有可导出的审计结果，请先执行一次审计','warning');
        }
    },

    _downloadBlob(data, format){
        const ts = new Date().toISOString().slice(0,19).replace(/[T:]/g,'');
        let content, filename, mime;
        if(format === 'md'){
            content = `# GEO 审计报告\n\n总分: ${data.total_score} | 等级: ${data.grade}\n\n` + JSON.stringify(data.dimensions, null, 2);
            filename = `GEO_Audit_${ts}.md`;
            mime = 'text/markdown';
        } else {
            content = JSON.stringify(data, null, 2);
            filename = `GEO_Audit_${ts}.json`;
            mime = 'application/json';
        }
        const blob = new Blob([content], {type:mime});
        const url = URL.createObjectURL(blob);
        const a=document.createElement('a'); a.href=url; a.download=filename;
        a.click(); URL.revokeObjectURL(url);
    },

    /** [A1] 保存审计结果到历史 */
    async saveAudit(){
        if(!this._lastAuditResult){
            toast('没有可保存的审计结果','warning'); return;
        }

        try{
            const saveData = {
                ...this._lastAuditResult,
                job_title: document.getElementById('auditJobSelect')?.options[document.getElementById('auditJobSelect')?.selectedIndex]?.textContent || '',
                source_job: {id: this._lastJobId}
            };

            const r = await API.post('/api/geo/audit/save', saveData);
            const d = r.data||{};

            if(d.success || d.saved_id){
                toast(`审计结果已保存 (${d.file_id})`,'success');
                document.getElementById('auditSaveBtn').disabled = true;
                this._loadHistory();
            } else {
                toast(d.error || '保存失败','error');
            }
        } catch(e){
            toast('保存失败: '+e.message,'error');
        }
    },

    /** [A1] 加载审计历史 */
    async _loadHistory(){
        const bodyEl = document.getElementById('auditHistoryBody');
        try{
            const r = await API.get('/api/geo/audit/history');
            const audits = r.data?.audits || [];

            if(!audits.length){
                bodyEl.innerHTML = '<p style="color:var(--text-muted);font-size:13px;">暂无审计历史。执行审计后点击"保存审计"即可在此查看。</p>';
                return;
            }

            bodyEl.innerHTML = audits.slice(0, 20).map(a => {
                const score = a.total_score || 0;
                const scoreColor = score >= 70 ? '#059669' : score >= 40 ? '#d97706' : '#dc2626';
                const icon = score >= 70 ? '✅' : score >= 40 ? '⚠️' : '❌';
                return `<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-color);">
                    <span style="font-size:18px;">${icon}</span>
                    <div style="flex:1;">
                        <div style="font-weight:600;font-size:13px;">${a.job_title || a.file_id || '审计记录'}</div>
                        <div style="font-size:11px;color:var(--text-muted);">${a.saved_at?.slice(0,19) || ''}</div>
                    </div>
                    <span class="tag ${(a.grade||'D').match(/^[AB]/)?'tag-green':'tag-red'}">${a.grade||'?'}</span>
                    <span style="font-weight:700;color:${scoreColor};">${score}</span>
                </div>`;
            }).join('');
        }catch(e){
            bodyEl.innerHTML = '<p style="color:var(--danger);">加载历史失败</p>';
        }
    },

    /** 从 Jobs 详情弹窗触发审计 */
    async auditFromDetail(){
        const jobId = document.getElementById('jobDetailRawId')?.value;
        if(jobId){
            switchPage('geo-audit');
            // 设置选中项并运行
            setTimeout(()=>{
                const sel = document.getElementById('auditJobSelect');
                if(sel) { sel.value = jobId; }
                this.run();
            }, 200);
        }
    },

    _renderScoreCard(audit){
        const score=audit.total_score||0;
        const grade=audit.grade||'D';
        const gradeColor={'A+':'#059669','A':'#059669','B+':'#2563eb','B':'#2563eb',
            'C':'#d97706','D':'#dc2626'}[grade]||'#999';
        
        document.getElementById('auditScoreCard').innerHTML=`
            <!-- 总分 -->
            <div class="phase-card" style="text-align:center;${''/* grid-column:1/-1 */}">
                <div style="font-size:36px;font-weight:800;color:${gradeColor};line-height:1;">${score}</div>
                <div style="color:var(--text-muted);font-size:12px;">总分 / 100</div>
                <div style="display:inline-block;margin-top:8px;padding:4px 16px;border-radius:20px;font-weight:700;
                    background:${gradeColor};color:#fff;font-size:14px;">${grade} 级</div>
                <div style="font-size:11px;color:var(--text-muted);margin-top:6px;">${audit.grade_label||''}</div>
            </div>

            ${Object.entries(audit.dimensions||{}).map(([key,dim])=>`
                <div class="phase-card">
                    <div style="font-size:13px;font-weight:600;margin-bottom:6px;">
                        ${key==='existence'? '🏗️ 存在层': key==='recommendation'? '⭐ 推荐层':
                          key==='conversion'? '🎯 转化层': '👑 品牌层'}
                    </div>
                    <div style="font-size:28px;font-weight:700;color:${dim.percentage>=70?'#059669':dim.percentage>=40?'#d97706':'#dc2626'}">
                        ${dim.percentage||0}<small style="font-size:12px;">%</small>
                    </div>
                    <div style="width:100%;height:6px;background:var(--gray-100);border-radius:3px;margin-top:8px;overflow:hidden;">
                        <div style="width:${dim.percentage||0}%;height:100%;background:${dim.percentage>=70?'#059669':dim.percentage>=40?'#d97706':'#dc2626'};border-radius:3px;"></div>
                    </div>
                    <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                        通过 ${(dim.checks||[]).filter(c=>c.passed).length}/${(dim.checks||[]).length}
                    </div>
                </div>
            `).join('')}
        `;
    },

    _renderDimensions(audit){
        const dims=audit.dimensions||{};
        const dimNames={
            existence:['存在层','🏗️','#1a73e8'],
            recommendation:['推荐层','⭐','#7c3aed'],
            conversion:['转化层','🎯','#059669'],
            brand:['品牌层','👑','#d97706']
        };
        
        const leftHtml=[];const rightHtml=[];
        let idx=0;
        for(const [key,dims_data] of Object.entries(dims)){
            const info=dimNames[key];
            if(!info) continue;
            const html=`
                <div class="card">
                    <div class="card-head">
                        <h3>${info[1]} ${info[0]}</h3>
                        <span style="font-weight:700;color:${info[2]};">${dims_data.percentage||0}%</span>
                    </div>
                    <div class="card-body">
                        ${(dims_data.checks||[]).map(c=>`
                            <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-color);">
                                <span style="font-size:16px;">${c.passed?'✅':'❌'}</span>
                                <span style="flex:1;font-size:13px;">${c.item}</span>
                                <span style="font-size:11px;color:var(--text-muted);">+${c.weight}分</span>
                            </div>
                        `).join('')}
                    </div>
                </div>`;
            if(idx<2) leftHtml.push(html);
            else rightHtml.push(html);
            idx++;
        }

        document.getElementById('auditDimensionsLeft').innerHTML=leftHtml.join('');
        document.getElementById('auditDimensionsRight').innerHTML=rightHtml.join('');
    },

    _renderSuggestions(audit){
        const suggestions=audit.suggestions||[];
        if(!suggestions.length){
            document.getElementById('auditSuggestionsArea').style.display='none';
            return;
        }
        document.getElementById('auditSuggestionsArea').style.display='';
        document.getElementById('auditSuggestionsList').innerHTML=suggestions.map(s=>{
            const dimIcon={existence:'🏗️',recommendation:'⭐',conversion:'🎯',brand:'👑'};
            return `
                <div style="display:flex;align-items:flex-start;gap:10px;padding:10px;margin-bottom:8px;
                    background:${s.priority==='high'?'rgba(220,38,38,0.04)':'rgba(217,119,6,0.04)'};
                    border-radius:8px;border-left:3px solid ${s.priority==='high'?'#dc2626':'#d97706'};">
                    <span>${dimIcon[s.dimension]||'📋'}</span>
                    <div style="flex:1;">
                        <div style="font-size:13px;">${s.item}</div>
                        <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">
                            ${s.priority==='high'?'高优先级 — 影响评分权重≥4分':'中优先级'}
                        </div>
                    </div>
                </div>`;
        }).join('');
    }
};


// ==================== 工具函数 ====================

/** [安全] HTML 转义 — 防止 XSS 注入到 innerHTML */
function esc(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** [安全] JS 字符串转义 — 用于 onclick 等属性中的动态值 */
function jsStr(str) {
    return JSON.stringify(String(str || ''));
}

function bar(label,value,max,gradient){
    return `<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
        <span style="min-width:55px;font-size:12px;">${label}</span>
        <div style="flex:1;height:20px;background:var(--gray-100);border-radius:4px;overflow:hidden;">
            <div style="height:100%;width:${value/max*100}%;background:linear-gradient(90deg,${gradient});border-radius:4px;"></div>
        </div>
        <span style="min-width:28px;text-align:right;font-size:12px;font-weight:600;">${value}</span>
    </div>`;
}

function renderPg(pg,containerId,callback){
    const el=document.getElementById(containerId);
    if(!el||!pg||pg.pages<=1){if(el)el.innerHTML='';return;}
    let h=`<button class="pg-btn" ${pg.page<=1?'disabled':''} onclick="${callback.name}(1)">«</button>`;
    for(let p=Math.max(1,pg.page-2);p<=Math.min(pg.pages,pg.page+2);p++)
        h+=`<button class="pg-btn ${p==pg.page?'on':''}" onclick="${callback.name}(${p})">${p}</button>`;
    h+=`<button class="pg-btn" ${pg.page>=pg.pages?'disabled':''} onclick="${callback.name}(${pg.pages})">»</button>`;
    el.innerHTML=h;
}

function toggleEl(id, show) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('hidden', !show);
}

// 全局暴露
window.runPipeline = ()=>Workflow.execute();
window.testConnection = ()=>Workflow.testDb();
window.toggleTheme = toggleTheme;
window.refreshData = refreshData;
window.generateSchema = ()=>Schema.generate();
window.copySchema = ()=>Schema.copy();
window.switchPage = switchPage;


// ==================== 关键词动态配置 ====================
var Keywords = window.Keywords = {
    _searchQueries: [],
    _brandKeywords: [],
    _pendingImport: null,  // 待确认导入的数据

    /** 加载关键词配置（从岗位数据自动提取） */
    async load() {
        try {
            const r = await API.get('/api/keywords');
            if (r.ok && r.data && r.data.success) {
                const data = r.data.data;
                this._searchQueries = data.search_queries || [];
                this._brandKeywords = data.brand_keywords || [];
                this._render();

                const sourceText = data.source === 'auto' ? '从岗位数据自动提取' :
                                   data.source === 'config' ? '从配置文件加载' : '默认词库';
                document.getElementById('keywordsStatus').innerHTML =
                    `<span style="color:#059669;">✓</span> ${this._searchQueries.length} 个搜索词, ${this._brandKeywords.length} 个品牌词 | ${sourceText}`;
            } else {
                document.getElementById('keywordsStatus').innerHTML =
                    `<span style="color:#dc2626;">✗</span> 加载失败: ${r.data?.message || '未知错误'}`;
            }
        } catch (e) {
            console.error('[Keywords] load error:', e);
            document.getElementById('keywordsStatus').innerHTML =
                `<span style="color:#dc2626;">✗</span> 加载失败: ${e.message}`;
        }
    },

    /** 重新从岗位数据提取关键词 */
    async refresh() {
        try {
            document.getElementById('keywordsStatus').textContent = '正在从岗位数据提取关键词...';
            const r = await API.post('/api/keywords/refresh', {});
            if (r.ok && r.data && r.data.success) {
                toast('关键词已从岗位数据重新提取！', 'success');
                await this.load();
            } else {
                toast('刷新失败: ' + (r.data?.message || '未知错误'), 'error');
            }
        } catch (e) {
            console.error('[Keywords] refresh error:', e);
            toast('刷新失败: ' + e.message, 'error');
        }
    },

    /** 渲染关键词标签列表 */
    _render() {
        // 渲染搜索关键词
        const sqEditor = document.getElementById('searchQueriesEditor');
        sqEditor.innerHTML = this._searchQueries.length > 0
            ? this._searchQueries.map((kw, i) => this._tagHtml(kw, 'search', i)).join('')
            : '<p style="color:var(--text-muted);padding:16px;">暂无搜索关键词，请先上传岗位数据</p>';
        document.getElementById('searchQueriesCount').textContent = `${this._searchQueries.length} 个`;

        // 渲染品牌关键词
        const bkEditor = document.getElementById('brandKeywordsEditor');
        bkEditor.innerHTML = this._brandKeywords.length > 0
            ? this._brandKeywords.map((kw, i) => this._tagHtml(kw, 'brand', i)).join('')
            : '<p style="color:var(--text-muted);padding:16px;">暂无品牌关键词，请先上传岗位数据</p>';
        document.getElementById('brandKeywordsCount').textContent = `${this._brandKeywords.length} 个`;
    },

    /** 生成单个关键词标签 HTML */
    _tagHtml(kw, type, index) {
        const bgColor = type === 'search' ? 'var(--blue-light, #e0f2fe)' : 'var(--orange-light, #fef3c7)';
        const textColor = type === 'search' ? '#0369a1' : '#b45309';
        return `<div class="kw-tag" style="display:inline-flex;align-items:center;gap:6px;padding:4px 12px;background:${bgColor};color:${textColor};border-radius:16px;font-size:13px;margin:4px;">
            <span>${this._escHtml(kw)}</span>
            <button onclick="Keywords.removeKeyword('${type}', ${index})" style="background:none;border:none;cursor:pointer;color:${textColor};opacity:0.6;font-size:16px;line-height:1;padding:0;">×</button>
        </div>`;
    },

    /** 转义 HTML 特殊字符 */
    _escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    /** 添加搜索关键词 */
    addSearchQuery() {
        const input = document.getElementById('newSearchQuery');
        const kw = input.value.trim();
        if (kw && !this._searchQueries.includes(kw)) {
            this._searchQueries.push(kw);
            this._render();
        }
        input.value = '';
    },

    /** 添加品牌关键词 */
    addBrandKeyword() {
        const input = document.getElementById('newBrandKeyword');
        const kw = input.value.trim();
        if (kw && !this._brandKeywords.includes(kw)) {
            this._brandKeywords.push(kw);
            this._render();
        }
        input.value = '';
    },

    /** 删除关键词 */
    removeKeyword(type, index) {
        if (type === 'search') {
            this._searchQueries.splice(index, 1);
        } else {
            this._brandKeywords.splice(index, 1);
        }
        this._render();
    },

    /** 清空搜索关键词 */
    clearSearchQueries() {
        if (confirm('确定要清空所有搜索关键词吗？')) {
            this._searchQueries = [];
            this._render();
        }
    },

    /** 清空品牌关键词 */
    clearBrandKeywords() {
        if (confirm('确定要清空所有品牌关键词吗？')) {
            this._brandKeywords = [];
            this._render();
        }
    },

    /** 处理文件上传 */
    handleFileUpload(event) {
        const file = event.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            const content = e.target.result;
            const lines = content.split(/\r?\n/).filter(l => l.trim());

            // 判断是否为 CSV 格式
            const isCSV = lines[0] && lines[0].includes(',');
            let searchQueries = [], brandKeywords = [];

            if (isCSV) {
                // CSV 格式: keyword,type
                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].trim();
                    if (!line) continue;
                    if (i === 0 && line.toLowerCase().includes('keyword')) continue; // 跳过表头
                    const parts = line.split(',');
                    const kw = parts[0].trim();
                    const type = parts[1]?.trim().toLowerCase() || 'search_query';
                    if (kw) {
                        if (type === 'brand_keyword') {
                            brandKeywords.push(kw);
                        } else {
                            searchQueries.push(kw);
                        }
                    }
                }
            } else {
                // TXT 格式: 根据选择的类型决定
                const importType = document.getElementById('importKeywordType').value;
                for (const line of lines) {
                    const kw = line.trim();
                    if (kw) {
                        if (importType === 'brand_keyword') {
                            brandKeywords.push(kw);
                        } else {
                            searchQueries.push(kw);
                        }
                    }
                }
            }

            // 显示预览
            this._pendingImport = { searchQueries, brandKeywords };
            const preview = document.getElementById('uploadPreview');
            const previewCount = document.getElementById('uploadPreviewCount');
            preview.style.display = 'block';
            previewCount.textContent = `将导入 ${searchQueries.length} 个搜索词，${brandKeywords.length} 个品牌词`;
        };
        reader.readAsText(file);

        // 清空 input 以便重复选择同一文件
        event.target.value = '';
    },

    /** 确认导入 */
    confirmImport() {
        if (!this._pendingImport) return;
        this._searchQueries = this._pendingImport.searchQueries;
        this._brandKeywords = this._pendingImport.brandKeywords;
        this._pendingImport = null;
        document.getElementById('uploadPreview').style.display = 'none';
        this._render();
        toast('导入成功！请点击"保存配置"以保存更改。', 'success');
    },

    /** 保存配置 */
    async save() {
        try {
            document.getElementById('keywordsStatus').textContent = '正在保存...';
            const r = await API.post('/api/keywords/save', {
                search_queries: this._searchQueries,
                brand_keywords: this._brandKeywords,
                save_to_db: false
            });

            if (r.ok && r.data && r.data.success) {
                document.getElementById('keywordsStatus').textContent =
                    `已保存: ${r.data.message}`;
                toast('关键词配置已保存！', 'success');
            } else {
                document.getElementById('keywordsStatus').textContent = '保存失败: ' + (r.data?.message || '未知错误');
                toast('保存失败: ' + (r.data?.message || '未知错误'), 'error');
            }
        } catch (e) {
            console.error('[Keywords] save error:', e);
            document.getElementById('keywordsStatus').textContent = '保存失败: ' + e.message;
            toast('保存失败: ' + e.message, 'error');
        }
    }
};


// ==================== 初始化 ====================
(function init(){
    applyTheme();
    Workflow.initUpload();

    // 左侧导航点击
    document.querySelectorAll('.nav-icon-btn[data-page]').forEach(btn=>{
        btn.addEventListener('click',()=>switchPage(btn.dataset.page));
    });

    // [A-03] 全局键盘快捷键导航 (Alt+数字快速切换页面)
    const pageMap = {'1':'workflow','2':'jobs','3':'geo-framework','4':'geo-audit','5':'schema','6':'monitor','7':'config','8':'keywords'};
    document.addEventListener('keydown', (e) => {
        if(e.altKey && !e.ctrlKey && !e.metaKey && pageMap[e.key]){
            e.preventDefault();
            switchPage(pageMap[e.key]);
        }
    });

    // 加载默认页数据
    Workflow.loadStats();

    // 定时刷新DB状态(60s) - 性能优化：延长刷新间隔
    setInterval(async()=>{
        // 只在页面可见时刷新，避免后台无意义请求
        if(document.visibilityState==='visible'){
            const r=await API.get('/api/status');
            const badge=document.getElementById('dbStatus');
            if(badge&&r.data?.database){
                if(r.data.database.connected){
                    badge.className='status-pill online';badge.innerHTML='<span class="status-dot"></span>DB 已连接';
                }else{
                    badge.className='status-pill offline';badge.innerHTML='<span class="status-dot"></span>未连接';
                }
            }
            // [L-01] 自动刷新当前可见页的统计数据 (仅 workflow 页)
            const curPage = document.querySelector('.page:not(.hidden)')?.id;
            if(curPage === 'page-workflow') Workflow.loadStats();
        }
    },60000); // 改为60秒

    function applyTheme(){
        document.body.dataset.theme=State.theme;
        const b=document.querySelector('.nav-icon-btn:last-child:not([onclick])');
        if(b&&!b.onclick)b.innerHTML=State.theme==='dark'?'☀️':'🌙';
    }

    // ============================================================
    // 系统状态模块 (Status) - 刷新系统状态详情
    // ============================================================
    var Status = window.Status = {
        /** 加载系统状态详情 */
        async load() {
            const table = document.getElementById('sysStatusTable');
            if (!table) return;
            
            table.innerHTML = '<tr><th>组件</th><th>状态</th><th>详情</th></tr><tr><td colspan="3" style="text-align:center;padding:20px;">加载中...</td></tr>';
            
            try {
                const r = await API.get('/api/status');
                if (!r.ok) throw new Error(r.error);
                
                const d = r.data || {};
                const components = [
                    { name: 'GEO Pipeline', status: 'ok', detail: `版本 ${d.version || 'v2.0.0'}` },
                    { name: 'Web UI', status: 'ok', detail: d.web_ui ? '已启用' : '未启用' },
                    { name: '数据库', status: d.database?.connected ? 'ok' : 'error', detail: d.database?.type || '-' },
                    { name: '运行时', status: 'ok', detail: d.runtime || '-' },
                    { name: '最后更新', status: 'ok', detail: d.last_run ? new Date(d.last_run).toLocaleString('zh-CN') : '-' }
                ];
                
                table.innerHTML = '<tr><th>组件</th><th>状态</th><th>详情</th></tr>' + 
                    components.map(c => `<tr><td>${c.name}</td><td><span class="tag ${c.status==='ok'?'tag-green':c.status==='warn'?'tag-orange':'tag-red'}">${c.status==='ok'?'正常':c.status==='warn'?'警告':'错误'}</span></td><td>${c.detail}</td></tr>`).join('');
            } catch (e) {
                table.innerHTML = '<tr><th>组件</th><th>状态</th><th>详情</th></tr><tr><td colspan="3" style="text-align:center;color:#dc2626;">加载失败: '+esc(e.message)+'</td></tr>';
            }
        }
    };

    // ============================================================
    // 实时日志窗口 (LogWindow) - 独立弹窗 + SSE 流式推送
    // ============================================================
    var LogWindow = window.LogWindow = {
    _eventSource: null,
    _logCount: 0,
    _maxLines: 300,
    _isOpen: false,
    _connected: false,
    _logs: [],

    /** 切换显示/隐藏 */
    toggle() {
        if (this._isOpen) this.hide();
        else this.show();
    },

    /** 显示日志窗口 */
    show() {
        if (this._isOpen) {
            const modal = document.getElementById('logWindowModal');
            if (modal) modal.style.display = 'flex';
            return;
        }
        this._isOpen = true;
        this._createModal();
        this._connectSSE();
        this._updateBtn(true);
    },

    /** 隐藏日志窗口 */
    hide() {
        const modal = document.getElementById('logWindowModal');
        if (modal) modal.style.display = 'none';
        this._isOpen = false;
        this._updateBtn(false);
    },

    /** 关闭并销毁 */
    close() {
        this._disconnect();
        const modal = document.getElementById('logWindowModal');
        if (modal) modal.remove();
        this._isOpen = false;
        this._logs = [];
        this._updateBtn(false);
    },

    /** 创建弹窗 */
    _createModal() {
        const html = `
        <div id="logWindowModal" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:3000;display:flex;align-items:center;justify-content:center;" onclick="LogWindow._backdrop(event)">
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:12px;width:95%;max-width:900px;height:80vh;display:flex;flex-direction:column;box-shadow:0 25px 80px rgba(0,0,0,0.5);" onclick="event.stopPropagation()">
                <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:linear-gradient(180deg,#161b22,#0d1117);border-bottom:1px solid #30363d;">
                    <div style="display:flex;align-items:center;gap:10px;">
                        <span style="font-size:20px;">💻</span>
                        <span style="color:#c9d1d9;font-weight:600;font-size:15px;">实时调试日志</span>
                        <span id="logStatus" style="font-size:11px;color:#8b949e;">◐ 连接中...</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span id="logCount" style="font-size:11px;color:#8b949e;background:#21262d;padding:2px 8px;border-radius:10px;">0 条</span>
                        <button onclick="LogWindow.clear()" style="background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:4px 8px;cursor:pointer;font-size:12px;">清空</button>
                        <button onclick="LogWindow.close()" style="background:#21262d;border:1px solid #30363d;color:#c9d1d9;border-radius:4px;padding:4px 8px;cursor:pointer;font-size:12px;">×</button>
                    </div>
                </div>
                <div id="logContent" style="flex:1;overflow-y:auto;padding:12px 16px;background:#0d1117;font-family:'SF Mono',Consolas,monospace;font-size:12px;line-height:1.6;">
                    <div style="color:#4ade80;text-align:center;padding:40px;">
                        <div>╔═══════════════════════════════════════╗</div>
                        <div>║   GEO Pipeline v2.0 - 实时日志终端   ║</div>
                        <div>╚═══════════════════════════════════════╝</div>
                        <div style="color:#58a6ff;margin-top:12px;">▶ 等待日志数据...</div>
                    </div>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', html);
    },

    /** 连接 SSE */
    _connectSSE() {
        if (this._eventSource) this._eventSource.close();
        try {
            this._eventSource = new EventSource('/api/logs/stream');
            this._eventSource.onopen = () => {
                this._connected = true;
                this._updateStatus('● 已连接', true);
            };
            this._eventSource.onmessage = (e) => {
                try {
                    const log = JSON.parse(e.data);
                    this._addLog(log);
                } catch {}
            };
            this._eventSource.onerror = () => {
                this._connected = false;
                this._updateStatus('✕ 连接断开', false);
                setTimeout(() => { if (!this._connected) this._connectSSE(); }, 3000);
            };
        } catch (e) {
            this._updateStatus('✕ 连接失败', false);
        }
    },

    /** 断开 SSE */
    _disconnect() {
        if (this._eventSource) {
            this._eventSource.close();
            this._eventSource = null;
        }
        this._connected = false;
    },

    /** 添加日志 - 性能优化版：限制 DOM 节点数量 */
    _addLog(log) {
        this._logCount++;
        this._logs.push(log);
        if (this._logs.length > this._maxLines) {
            this._logs.shift();
        }
        
        const content = document.getElementById('logContent');
        if (!content) return;
        
        // 移除欢迎信息
        const welcome = content.querySelector('div[style*="text-align:center"]');
        if (welcome) welcome.remove();

        const time = log.timestamp ? new Date(log.timestamp).toLocaleTimeString('zh-CN',{hour12:false}) + '.' + String(new Date(log.timestamp).getMilliseconds()).padStart(3,'0') : '';
        const lvl = log.level || 'INFO';
        const lvlColors = {DEBUG:'#6e7681',INFO:'#58a6ff',WARN:'#d29922',ERROR:'#f85149'};
        const src = log.source || 'System';
        const msg = this._esc(log.message || '');
        
        const isSuccess = msg.includes('完成') || msg.includes('成功') || msg.includes('✅');
        const isErr = lvl === 'ERROR';
        const msgColor = isErr ? '#f85149' : isSuccess ? '#3fb950' : '#c9d1d9';

        let dataHtml = '';
        if (log.data && Object.keys(log.data).length > 0) {
            const pairs = Object.entries(log.data).slice(0,4).map(([k,v]) => 
                `<span style="color:#79c0ff">${this._esc(k)}:</span> <span style="color:#a5d6ff">${this._esc(String(v).substring(0,80))}</span>`
            ).join(' &nbsp; ');
            dataHtml = `<div style="margin-top:6px;padding:6px 8px;background:#161b22;border-radius:4px;font-size:11px;color:#8b949e;">${pairs}</div>`;
        }

        const line = `<div style="display:flex;gap:8px;padding:3px 0;border-bottom:1px solid #21262d;animation:fadeIn .2s">
            <span style="color:#6e7681;flex-shrink:0">${time}</span>
            <span style="color:${lvlColors[lvl]||'#6e7681'};flex-shrink:0;font-weight:600;width:45px">${lvl}</span>
            <span style="color:#8b949e;flex-shrink:0;width:65px">${this._esc(src)}</span>
            <span style="color:${msgColor};flex:1">${msg}</span>
        </div>${dataHtml}`;
        
        content.insertAdjacentHTML('beforeend', line);
        
        // 性能优化：限制 DOM 节点数量，超过则批量移除旧节点
        const maxVisibleLines = 200;
        const children = content.children;
        while (children.length > maxVisibleLines) {
            children[0].remove();
        }
        
        // 节流滚动：只在日志较少时自动滚动
        if (this._logCount < 100) {
            content.scrollTop = content.scrollHeight;
        }
        
        const cnt = document.getElementById('logCount');
        if (cnt) cnt.textContent = `${this._logCount} 条`;
    },

    /** 写入自定义日志 */
    log(message, level = 'INFO', source = 'App') {
        this._addLog({timestamp: new Date().toISOString(), level, source, message});
    },

    /** 清空日志 */
    clear() {
        this._logCount = 0;
        this._logs = [];
        const content = document.getElementById('logContent');
        if (content) {
            content.innerHTML = `<div style="color:#4ade80;text-align:center;padding:40px;">
                <div>╔═══════════════════════════════════════╗</div>
                <div>║   GEO Pipeline v2.0 - 实时日志终端   ║</div>
                <div>╚═══════════════════════════════════════╝</div>
                <div style="color:#58a6ff;margin-top:12px;">▶ 日志已清空</div>
            </div>`;
        }
        const cnt = document.getElementById('logCount');
        if (cnt) cnt.textContent = '0 条';
    },

    /** 更新状态文本 */
    _updateStatus(text, ok) {
        const el = document.getElementById('logStatus');
        if (el) { el.textContent = text; el.style.color = ok ? '#3fb950' : '#f85149'; }
    },

    /** 更新按钮状态 */
    _updateBtn(active) {
        const btn = document.getElementById('logWindowBtn');
        if (btn) btn.style.background = active ? '#2563eb' : '';
        if (btn) btn.style.color = active ? 'white' : '';
    },

    /** 点击背景关闭 */
    _backdrop(e) {
        if (e.target === e.currentTarget) this.hide();
    },

    /** HTML转义 */
    _esc(s) { if(!s)return''; const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
    };

    // 页面加载完成后不自动打开日志窗口 (性能优化)
    // document.addEventListener('DOMContentLoaded', () => { LogWindow.show(); });

    // 暴露全局函数 (供 HTML onclick 调用)
    window.switchPage = switchPage;
    window.refreshData = refreshData;
    window.toggleTheme = toggleTheme;
})();
