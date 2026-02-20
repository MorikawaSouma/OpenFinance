# OpenFinance Frontend Design System

## 1) Visual Direction
- Direction: `data-informed editorial` (清晰层级 + 明确状态色 + 高可读密度)
- Goal: 让 Chat 与 Reports 从“工程面板”提升为“可交付 SaaS 工作台”

## 2) Design Tokens
- Typography
  - Global font chain:
    - `"Inter", "Noto Sans SC", system-ui, -apple-system, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`
  - Applied in:
    - `frontend/src/app/layout.tsx`
    - `frontend/src/app/globals.css`
    - `frontend/tailwind.config.js`
- Spacing scale
  - `--space-1/2/3/4/5/6/8/10/12`
- Radius
  - `--radius` + Tailwind `lg/md/sm` mapping
- Color roles
  - `primary / secondary / success / warning / destructive`
  - Dark mode keeps semantic mapping unchanged
- Elevation
  - `shadow-soft` + card/backdrop blend for panel hierarchy

## 3) Component Standards
- Unified component system: `shadcn/ui` (Card, Button, Badge, Table, Tabs, Sheet, Toast)
- Unified states
  - EmptyState: 中文自然语气 + 下一步建议
  - Loading: skeleton + “执行中/对比中/恢复中”
  - Error: toast 统一中文反馈
- List behavior
  - Sessions / Approvals / Risk Events / Runs:
    - hover highlight
    - selected state
    - timestamp format via locale
    - long text truncate

## 4) Information Architecture
- Chat Workspace
  - Answer-first rendering
  - 可折叠卡片（Plan/Experiments/Evidence/Decision）
  - Developer Mode 才显示 Raw Payload / Prompt / Response / ReasoningTrace
- Trading Console
  - 分区：实盘锁状态、纸交易控制、审批流、风险事件
  - 关键状态用 badge，减少长文本堆叠
- Reports
  - Tab 化：运行列表 / 运行对比 / 跨市场 / 稳健性
  - 空状态与操作提示统一

## 5) Glossary (术语统一)
- `EvidencePack` = `证据包`
- `Plan` = `研究计划`
- `Run` = `回测运行`
- `Robustness` = `稳健性`
- `Approval` = `审批`
- `Risk Gate` = `实盘锁`
