# OpenFinance

OpenFinance 是一个面向量化研究与风控演练的全栈工作台（monorepo），包含：
- `FastAPI` 后端（研究计划、回测、因子验证、风控审批、SSE 事件流）
- `Next.js` 前端（可视化工作台：Dashboard/Chat/Pipeline/Reports/Risk）
- 本地可追踪数据层（数据集、run、审计链、证据包、聊天会话）

默认配置可离线跑通（`LLM stub` 模式），不需要先接入真实 LLM Key。

## 功能概览

- 一键生成 mock 数据集并注册版本
- 回测任务异步执行（任务状态可轮询 / 实时事件可订阅）
- Pipeline 端到端：`plan -> evidence -> factor -> strategy -> backtest`
- Chat 会话式研究（含会话记忆、run 对比、trace 恢复）
- Reports 页面查看指标、净值曲线、归因、订单与成交
- RiskGate 审批流与 kill-switch（默认 live 关闭）

## 仓库结构

```text
OpenFinance/
  backend/                 # FastAPI + research/backtest/trading engine
  frontend/                # Next.js workbench UI
  infra/scripts/           # 启停、重置、验收脚本
  shared/contracts/        # 共享接口约定
  .openfinance/            # 本地产物目录（运行后生成）
  .runlogs/                # 本地日志目录（运行后生成）
```

## 环境要求

- Python `3.11+`
- Node.js `18+`
- npm `9+`
- 可选：`make`（Windows 用户可直接使用 `start_dev.bat`）

## 快速上手（推荐流程）

### 1) 克隆项目

```bash
git clone <your-repo-url>
cd OpenFinance
```

### 2) 配置环境变量

```powershell
Copy-Item .env.example .env
```

默认 `.env.example` 已开启：
- `OPENFINANCE_LLM_FORCE_STUB=true`

如果要接入真实智谱模型，可修改：
- `OPENFINANCE_LLM_FORCE_STUB=false`
- `OPENFINANCE_ZHIPU_API_KEY=<your_key>`

### 3) 安装依赖

方式 A（有 make）：

```bash
make backend-install
make frontend-install
```

方式 B（无 make）：

```powershell
cd backend
python -m pip install -e ".[dev]"
cd ../frontend
npm install
cd ..
```

### 4) 启动服务

Windows 一键启动（推荐）：

```bat
start_dev.bat
```

通用方式：

```bash
make dev
```

说明：
- `start_dev.bat` 会调用 `infra/scripts/start_dev.ps1 -Restart`
- 当 `3000/8000` 端口被占用时，会自动回退到可用端口并写入 `.runlogs/dev.ports`

### 5) 验证服务

如果使用一键启动，先看实际端口：

```powershell
Get-Content .runlogs/dev.ports
```

默认地址（未回退时）：
- 前端：`http://127.0.0.1:3000`
- 后端文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/healthz`

### 6) 停止服务

```powershell
powershell -ExecutionPolicy Bypass -File infra/scripts/stop_dev.ps1
```

## 5 分钟体验（前端）

1. 打开 Dashboard：`/`
2. 点击 `Generate Dataset`
3. 点击 `Run Backtest`
4. 打开 `Tasks`（`/tasks`）观察任务状态变为 `done`
5. 打开 `Reports`（`/reports`）进入最新 run 详情
6. 在 `Chat`（`/chat`）提问，查看研究结论与证据引用

## API 使用示例（PowerShell）

> 假设后端在 `http://127.0.0.1:8000`。若你使用了端口回退，请替换为实际端口。

### 示例 1：生成数据集 -> 跑回测 -> 查看报告

```powershell
$api = "http://127.0.0.1:8000"

function Wait-TaskDone([string]$taskId) {
  do {
    Start-Sleep -Seconds 1
    $task = Invoke-RestMethod -Method Get -Uri "$api/workbench/tasks/$taskId"
    Write-Host "[$($task.status)] $($task.progress)% - $($task.message)"
  } while ($task.status -notin @("done", "failed"))
  return $task
}

$dsTask = Invoke-RestMethod -Method Post -Uri "$api/workbench/datasets/generate" -ContentType "application/json" -Body (@{
  dataset_id = "wb_demo"
  market = "US"
  symbol = "AAPL"
  start = "2024-01-01"
  end = "2024-02-01"
  seed = 1
  base_price = 100
} | ConvertTo-Json)

$dsFinal = Wait-TaskDone $dsTask.task_id
if ($dsFinal.status -eq "failed") { throw "dataset task failed" }
$datasetVersion = $dsFinal.result.dataset_version

$btTask = Invoke-RestMethod -Method Post -Uri "$api/workbench/backtests/run" -ContentType "application/json" -Body (@{
  dataset_version = $datasetVersion
  strategy_id = "demo"
  strategy_version = "0.1.0"
  market = "US"
  start = "2024-01-01"
  end = "2024-02-01"
} | ConvertTo-Json)

$btFinal = Wait-TaskDone $btTask.task_id
if ($btFinal.status -eq "failed") { throw "backtest task failed" }
$runId = $btFinal.result.run_id

$report = Invoke-RestMethod -Method Get -Uri "$api/workbench/reports/$runId"
$report.metrics
```

### 示例 2：聊天接口 + 会话历史

```powershell
$api = "http://127.0.0.1:8000"

$chat = Invoke-RestMethod -Method Post -Uri "$api/chat/message" -ContentType "application/json" -Body (@{
  message = "为什么最近日经波动大？给我高夏普低回撤策略并附回测要点。"
} | ConvertTo-Json)

$chat.assistant_message
$sessionId = $chat.session_id
Invoke-RestMethod -Method Get -Uri "$api/chat/sessions/$sessionId"
```

### 示例 3：直接跑 Pipeline

```powershell
$api = "http://127.0.0.1:8000"

$pipe = Invoke-RestMethod -Method Post -Uri "$api/run" -ContentType "application/json" -Body (@{
  question = "给我一套低回撤策略并做三组实验对比"
  market = "US"
  run_paper_trade = $true
  experiments = 3
} | ConvertTo-Json)

$pipe.plan_id
$pipe.run_id
$pipe.backtest_metrics
```

## 如何查看结果

### 在前端页面看

- `Dashboard (/)`：最近 run、快速操作入口
- `Tasks (/tasks)`：任务执行进度与错误信息
- `Datasets (/datasets)`：数据集版本与质量摘要
- `Reports (/reports)`：回测列表、对比、多市场/稳健性分析
- `Report Detail (/reports/{runId})`：指标、曲线、成交、归因、证据引用
- `Pipeline (/pipeline)`：端到端时间线与计划快照
- `Chat (/chat)`：问答、会话历史、开发模式调试面板
- `Risk (/risk)`：审批流、风险事件、kill switch、模拟 live 日志
- `Evidence (/evidence)`：证据包与来源可信度

### 在本地文件看

- 数据集注册：`.openfinance/registry/datasets.jsonl`
- 回测注册：`.openfinance/registry/runs.jsonl`
- 研究计划注册：`.openfinance/registry/plans.jsonl`
- 审计链：`.openfinance/registry/audit.jsonl`
- 聊天会话：`.openfinance/registry/chat_sessions.json`
- 证据库：`.openfinance/registry/evidence.sqlite3`
- 风控审批：`.openfinance/registry/approvals.sqlite3`
- 数据与报告文件：`.openfinance/data/*.json`
- 因子产物：`.openfinance/artifacts/factors/*.json` 与 `*.health.json`
- 启动日志：`.runlogs/backend.out.log`、`.runlogs/frontend.out.log`

## 常用开发命令

```bash
# 启动
make dev

# 后端测试
make backend-test

# 前端 E2E
cd frontend && npm run test:e2e

# 重置本地产物（会删除 .openfinance 和 .runlogs）
make dev-reset
# 或
python infra/scripts/dev_reset.py --yes
```

## 常见问题

### 1) 报错 `no dataset available; generate one first`

先生成数据集，再跑回测：
- 前端点 `Generate Dataset`
- 或调用 `POST /workbench/datasets/generate`

### 2) 前端连不上后端

- 检查后端健康：`/healthz`
- 查看 `.runlogs/dev.ports` 确认实际端口
- 手动启动前端时，设置 `NEXT_PUBLIC_API_BASE=http://127.0.0.1:<backend_port>`

### 3) 想用真实 LLM，不想用 stub

在 `.env` 中设置：
- `OPENFINANCE_LLM_FORCE_STUB=false`
- `OPENFINANCE_ZHIPU_API_KEY=<your_key>`

### 4) 如何彻底清理本地状态

执行：

```bash
python infra/scripts/dev_reset.py --yes
```

## 安全默认策略

- `live trading` 默认关闭
- 需要审批状态机才能 enable（`pending -> approved -> enabled`）
- 支持 `kill switch` 一键阻断


