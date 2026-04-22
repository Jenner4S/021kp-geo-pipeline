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
const Workflow = {

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
const Jobs = {
    _debounceTimer: null,
    _currentJob: null,   // [J2] 当前查看的岗位详情
    /** 刷新列表（供404错误页的"刷新"按钮调用） */
    _refreshList(){ this.load(Jobs._currentPage||1); },
    async load(page=1){
        // [J4] 获取分类筛选
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
            <tr>
                <td><code style="font-size:11px">${esc(j.id)||(page-1)*20+i+1}</code></td>
                <td><strong style="cursor:pointer;color:var(--primary);" onclick="Jobs.showDetail('${encodeURIComponent(esc(j.id))}')" title="点击查看详情">${esc(j.title)||'-'}</strong></td>
                <td>${esc(j.company)||'-'}</td>
                <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px">${esc(j.location)||'-'}</td>
                <td class="salary-text">¥${j.min_salary||0}-¥${j.max_salary||0}</td>
                <td><span class="tag tag-blue">${esc(j.category)||'-'}</span></td>
                <td>${j.is_urgent?'<span class="tag tag-red">急招</span>':'<span style="color:var(--text-muted)">否</span>'}</td>
                <td>
                    <div style="display:flex;gap:4px;">
                        <button class="btn-outline btn-sm" onclick="Schema.fromJob(${jsStr(esc(j.title))})" title="Schema预览">预览</button>
                        <button class="btn-outline btn-sm" onclick="Jobs.showDetail('${encodeURIComponent(esc(j.id))}')" title="查看详情">详情</button>
                        <!-- [J1] 删除按钮 -->
                        <button class="btn-outline btn-sm" style="color:#dc2626;border-color:#dc2626;" onclick="Jobs.deleteJob(${jsStr(j.id)},${jsStr(esc(j.title))})"
                            title="删除此岗位">🗑</button>
                    </div>
                </td>
            </tr>`).join('');

        renderPg(r.data.pagination,'jobsPagination',Jobs.load);
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

            // 渲染详情字段
            const fields = [
                ['ID', j.id], ['标题', j.title], ['企业', j.company],
                ['地点', j.location], ['最低薪资', `¥${j.min_salary||0}`],
                ['最高薪资', `¥${j.max_salary||0}`], ['分类', j.category],
                ['急招', j.is_urgent ? '是' : '否'], ['要求', j.requirements || '-'],
                ['福利', j.benefits || '-'],
            ];

            body.innerHTML = fields.map(([label, val]) => `
                <div class="job-detail-field">
                    <span class="job-detail-label">${label}</span>
                    <span class="job-detail-value">${esc(val)||'-'}</span>
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
const Schema = {
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
const Monitor = {
    _citationData: null,
    _alertsData: null,
    _autoRefreshTimer: null,   // [L-02] 自动刷新定时器

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
            document.getElementById('citationMetricsGrid').innerHTML=
                '<div style="grid-column:1/-1;color:var(--text-muted);font-size:13px;text-align:center;padding:30px 0;">暂无检测数据，点击「执行引用率检测」获取</div>';
            return;
        }

        // 各平台卡片
        const trendIcons={rising:'\uD83D\uDCC8',stable:'27A1\uFE0F',falling:'\uD83D\uDCC9',unknown:'❓'};
        document.getElementById('citationMetricsGrid').innerHTML=metrics.map(m=>{
            const pct=m.citation_rate;
            const color=pct>=1?'#059669':pct>=0.5?'#d97706':'#dc2626';
            return `
            <div class="phase-card" style="border-left:3px solid ${color};">
                <div style="font-weight:600;font-size:14px;">${esc(m.platform).toUpperCase()}</div>
                <div style="display:flex;align-items:baseline;gap:4px;margin:8px 0;">
                    <span style="font-size:28px;font-weight:800;color:${color}">${pct.toFixed(2)}</span>
                    <span style="font-size:12px;color:var(--text-muted);">%</span>
                    <span>${trendIcons[m.trend]||''}</span>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text-muted);">
                    <span>提及 ${m.brand_mention_count} 次</span>
                    <span>查询 ${m.total_queries}</span>
                </div>
                ${m.citation_rate<0.5?`<div style="margin-top:6px;font-size:11px;color:#dc2626;">⚠ 低于阈值(0.5%)</div>`:''}
            </div>`}).join('');

        // 趋势摘要
        const avg=data.avg_citation_rate||0;
        const summaryEl=document.getElementById('citationTrendSummary');
        summaryEl.style.display='';
        summaryEl.innerHTML=`<strong>\uD83D\uDCCA 摘要:</strong> 共监测 ${esc(metrics.length)} 个平台，平均引用率 <strong style="color:${avg>=1?'#059669':avg>=0.5?'#d97706':'#dc2626'}">${avg.toFixed(3)}%</strong>，整体状态：<strong>${esc(statusMap[data.overall_status])}</strong> · 检测时间：${esc(data.checked_at)||'-'} · ${data.overall_status==='FROZEN'?`<span style="color:#dc2626;">⚡ 已触发自动回滚保护机制</span>`:''}`;
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
            body.innerHTML='<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px 0;">✅ 近期无告警，系统运行正常</div>';
            return;
        }

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
            body.innerHTML='<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px 0;">暂无监控报告。执行引用率检测后将自动生成。</div>';
            return;
        }

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

        // 更新面板为 loading 状态
        document.getElementById('citationMetricsGrid').innerHTML=
            '<div style="grid-column:1/-1;text-align:center;padding:30px 0;"><div style="animation:spin-dot 1s infinite;display:inline-block;">⏳</div><p style="color:var(--text-muted);margin-top:8px;">正在采集各平台引用率数据...</p></div>';

        try{
            const r=await API.post('/api/monitor/check');
            const d=r.data||{};

            if(d.error && d.status!=='error'){
                toast('检测完成（部分数据）','warning');
            } else if(d.status==='error'){
                throw new Error(d.error||'检测失败');
            }else{
                toast(`检查完成 | 状态: ${d.status} | ${d.alerts_triggered||0} 条告警`, d.rollback_executed?'warning':'success');
            }

            // 刷新所有面板
            await this.load();

        }catch(e){
            toast('检测失败: '+e.message,'error');
            document.getElementById('citationMetricsGrid').innerHTML=
                '<div style="grid-column:1/-1;color:var(--text-muted);font-size:13px;text-align:center;padding:30px 0;">❌ 检测失败，请检查服务日志</div>';
        }finally{
            btn.disabled=false;btn.textContent='🔍 执行引用率检测';
        }
    },

    /** 单独刷新回滚状态 */
    async loadRollback(){
        try{
            const r=await API.get('/api/monitor/rollback');
            this._renderRollbackPanel(r.data||{});
        }catch(e){toast('刷新失败:'+e.message,'error');}
    },

    /* ===== 保留原有基础统计渲染逻辑 ===== */

    _renderBasicStats(sr, str){
        const s=(sr&&sr.status==='fulfilled'?sr.data:{})?.data||str?.data||{};
        const sys=s.system||{};const db=s.database||{};
        const exec=s.execution||{}; // 历史记录由 _renderHistory 单独处理

        // 核心指标卡片 (精简版)
        document.getElementById('monitorCards').innerHTML=[
            { icon:'💼', title:'活跃岗位', value:s.total_active||0, sub:'待处理岗位数' },
            { icon:'✅', title:'合规通过率', value:`${exec.success_rate||0}%`, sub:`共${exec.total_executions||0}次执行` },
            { icon:'🔥', title:'急招岗位', value:s.urgent_count||0, sub:'优先推送到AI平台' },
            { icon:'🕐', title:'平均耗时', value:`${exec.avg_duration||0}s`, sub:'最近一次流水线' },
            { icon:'🗄️', title:'数据库', value:db.connected?'已连接':'未连接', sub:db.database||'-', cls:db.connected?'done':'pending' },
            { icon:'🐍', title:'Python', value:`v${sys.python_version||'-'}`, sub:sys.platform||'-' },
        ].map(c=>`
            <div class="phase-card">
                <div class="phase-icon">${c.icon}</div>
                <div class="phase-title">${c.title}</div>
                <div style="font-size:22px;font-weight:700;margin:6px 0 2px;">${c.value}</div>
                <div style="font-size:11px;color:var(--text-muted);">${c.sub}</div>
                ${c.cls?`<div class="phase-status ${c.cls}" style="margin-top:6px">${c.cls==='done'?'● 正常':'○ 待配置'}</div>`:''}
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
        if(filtered.length===0){listEl.innerHTML='';toggleEl('historyEmpty',true);return;}
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
const Config = {
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
        const type_ = (f.type_ || 'STRING').toUpperCase();

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
const GEOAudit = {
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


// ==================== 初始化 ====================
(function init(){
    applyTheme();
    Workflow.initUpload();

    // 左侧导航点击
    document.querySelectorAll('.nav-icon-btn[data-page]').forEach(btn=>{
        btn.addEventListener('click',()=>switchPage(btn.dataset.page));
    });

    // [A-03] 全局键盘快捷键导航 (Alt+数字快速切换页面)
    const pageMap = {'1':'workflow','2':'jobs','3':'geo-framework','4':'geo-audit','5':'schema','6':'monitor','7':'config'};
    document.addEventListener('keydown', (e) => {
        if(e.altKey && !e.ctrlKey && !e.metaKey && pageMap[e.key]){
            e.preventDefault();
            switchPage(pageMap[e.key]);
        }
    });

    // 加载默认页数据
    Workflow.loadStats();

    // 定时刷新DB状态(30s)
    setInterval(async()=>{
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
            // [L-01] 自动刷新当前可见页的统计数据
            const curPage = document.querySelector('.page:not(.hidden)')?.id;
            if(curPage === 'page-workflow') Workflow.loadStats();
        }
    },30000);

    function applyTheme(){
        document.body.dataset.theme=State.theme;
        const b=document.querySelector('.nav-icon-btn:last-child:not([onclick])');
        if(b&&!b.onclick)b.innerHTML=State.theme==='dark'?'☀️':'🌙';
    }
})();
