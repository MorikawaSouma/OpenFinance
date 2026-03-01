# OpenFinance

OpenFinance 是一个面向量化研究与风控演练的全栈工作台（monorepo），包含：

- `backend`：FastAPI 服务，负责研究计划、因子计算、策略选择、回测、风控审批、任务编排与 SSE 事件流。
- `frontend`：Next.js 工作台，提供 Chat、Pipeline、Tasks、Reports、Risk 等页面。
- `shared/contracts`：前后端共享事件/模型约定。

当前代码默认可离线运行（`LLM stub`），无需先配置真实大模型 Key。

## 现在支持的核心能力

- 异步长任务体系：`Chat -> 立即返回 task_id -> SSE/Tasks 跟踪 -> 完成后结果可回放`
- Pipeline 多阶段可观测：`task.created/progress/heartbeat/variant_started/variant_done/done/error`
- Parent/Child 任务：Tasks 页可看父任务与各变体子任务进度
- 任务状态可恢复：前端持久化活跃任务，切页/刷新后可继续恢复状态
- 市场上下文锁定：Pipeline 启动后 market 固化并传递到子任务与 run/report
- 迁移预检（preflight）：跨市场规则不匹配时先告警再确认
- Chat 风控快照同步：ChatResponse 返回 `risk_snapshot` 与 `approvals_snapshot`
- Developer Mode 可观测：Live Trace + Reasoning Steps（不暴露私有 CoT，仅暴露可审计摘要）

## 仓库结构

```text
OpenFinance/
  backend/                 # FastAPI + research/backtest/trading
  frontend/                # Next.js workbench UI
  infra/scripts/           # 启停、重置、验收脚本
  shared/contracts/        # 共享事件与模型契约
  .openfinance/            # 本地运行产物（运行后生成）
  .runlogs/                # 本地日志（运行后生成）
```

## 环境要求

- Python `3.11+`
- Node.js `18+`
- npm `9+`
- 可选：`make`（Windows 用户可直接使用 `start_dev.bat`）

## 快速启动

### 1) 克隆仓库

```bash
git clone https://github.com/MorikawaSouma/OpenFinance.git
cd OpenFinance
```

### 2) 配置环境变量

```powershell
Copy-Item .env.example .env
```

默认推荐保留：

- `OPENFINANCE_LLM_FORCE_STUB=true`

如果接入真实模型：

- `OPENFINANCE_LLM_FORCE_STUB=false`
- `OPENFINANCE_ZHIPU_API_KEY=<your_key>`

### 3) 安装依赖

方式 A（推荐，有 `make`）：

```bash
make backend-install
make frontend-install
```

方式 B（无 `make`）：

```powershell
cd backend
python -m pip install -e ".[dev]"
cd ../frontend
npm install
cd ..
```

### 4) 启动开发环境

Windows 一键启动（推荐）：

```bat
start_dev.bat
```

或跨平台：

```bash
make dev
```

说明：

- `start_dev.bat` 会调用 `infra/scripts/start_dev.ps1 -Restart`
- 若 `3000/8000` 被占用，会自动回退可用端口并写入 `.runlogs/dev.ports`

### 5) 访问地址

先查看实际端口：

```powershell
Get-Content .runlogs/dev.ports
```

默认地址（未回退时）：

- Frontend: `http://127.0.0.1:3000`
- Backend Docs: `http://127.0.0.1:8000/docs`
- Health Check: `http://127.0.0.1:8000/healthz`
- SSE Stream: `http://127.0.0.1:8000/events/stream`

### 6) 停止服务

```powershell
powershell -ExecutionPolicy Bypass -File infra/scripts/stop_dev.ps1
```

## 页面说明

- `/` Dashboard：最近运行概览、快捷操作
- `/chat` Chat：对话入口，支持 User/Developer 模式
- `/pipeline` Pipeline：研究流程触发与过程查看
- `/tasks` Tasks：父子任务树、进度、阶段、结果链接
- `/datasets` Datasets：数据集版本与摘要
- `/strategies` Strategies：策略版本与参数
- `/factors` Factors：因子版本与健康报告
- `/reports` Reports：回测列表与对比
- `/reports/{runId}` Report Detail：指标、净值、交易、归因
- `/evidence` Evidence：证据包与来源
- `/risk` Risk：审批流、锁状态、Kill Switch、风控事件
- `/settings` Settings：工作台配置

## 任务与事件模型

### 任务接口

- `GET /workbench/tasks`
- `GET /workbench/tasks/{task_id}`
- `POST /run/submit`
- `POST /pipeline/run/submit`
- `POST /workbench/backtests/run`
- `POST /workbench/factors/run/submit`

### SSE 关键事件

`shared/contracts/events.json` 中已定义主要事件类型：

- `task.created`
- `task.progress`
- `task.heartbeat`
- `task.variant_started`
- `task.variant_done`
- `task.done`
- `task.error`
- `agent.dispatched` / `agent.completed`
- `tool.call.started` / `tool.call.finished`
- `artifact.created`
- `reasoning.step.created` / `reasoning.step.updated`
- `reasoning.trace.final`
- `chat.delta` / `chat.done`

## Chat 与 Pipeline 的运行方式

### General Info（如“美股最近如何”）

- Chat 返回结论与引用
- Developer Mode 可看到 `Reasoning Steps`（意图识别、证据使用、结论综合）
- 任务会被正常闭环（创建后进入 done/error，不应长期停在 initializing）

### Pipeline（如“基于当前 JP 市场给我一个低回撤策略并回测”）

- Chat 立即返回 `accepted + task_id`
- 前端显示 Running Card，可跳转 Tasks
- Pipeline 运行中持续推送阶段/心跳/子任务进度
- 完成后结果写入任务 `result/result_ref`，可直接打开 Report/Evidence/Plan

## Developer Mode 说明

Developer Mode 面向调试和审计，不展示私有 CoT 原文，展示的是“可审计摘要”：

- Live Trace：agent/tool/artifact/audit 实时事件流
- Reasoning Steps：结构化步骤（hypothesis/evidence/counterevidence/revision/decision/warning）
- trace_id 追踪：支持 `GET /trace/{trace_id}/restore` 恢复上下文

## 本地数据与产物

常用路径（默认）：

- `.openfinance/registry/tasks.json`
- `.openfinance/registry/runs.jsonl`
- `.openfinance/registry/datasets.jsonl`
- `.openfinance/registry/plans.jsonl`
- `.openfinance/registry/audit.jsonl`
- `.openfinance/registry/chat_sessions.json`
- `.openfinance/registry/evidence.sqlite3`
- `.openfinance/registry/factors.sqlite3`
- `.openfinance/registry/approvals.sqlite3`
- `.openfinance/artifacts/factors/`
- `.runlogs/backend.out.log`
- `.runlogs/frontend.out.log`

## 测试与验收

后端测试：

```bash
make backend-test
```

或：

```powershell
cd backend
pytest
```

前端 E2E：

```powershell
cd frontend
npm run test:e2e
```

后端验收脚本（Windows）：

```powershell
powershell -ExecutionPolicy Bypass -File infra/scripts/acceptance_backend.ps1
```

## 常见问题

### 1) 前端连不上后端

- 检查 `GET /healthz`
- 检查 `.runlogs/dev.ports` 里的实际端口
- 确认 `NEXT_PUBLIC_API_BASE` 指向正确后端地址

### 2) 任务看起来卡住

- 刷新 `/tasks` 并查看该任务 `status/error`
- 检查 `.runlogs/backend.out.log` 与 `.openfinance/registry/tasks.json`
- 服务重启后，历史 `queued/running` 任务会被恢复为 `error`（防止“假运行”）

### 3) 想强制清理本地状态

```bash
make dev-reset
```

或：

```powershell
python infra/scripts/dev_reset.py --yes
```

## 安全默认

- `live trading` 默认关闭
- 支持审批流与状态迁移（pending/approved/enabled/revoked）
- 支持 `kill switch` 一键阻断

---

如果你是第一次看这个仓库，建议从以下路径开始阅读代码：

1. `backend/openfinance/api/routes_chat.py`
2. `backend/openfinance/research/pipeline.py`
3. `backend/openfinance/quant/backtest/runner.py`
4. `frontend/src/components/providers/workbench-provider.tsx`
5. `frontend/src/app/chat/page.tsx`
