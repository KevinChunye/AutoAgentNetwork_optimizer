# PHOENIX OpenAI smoke 与后续接续 — 2026-10-31

真实接入测试通过；正式实验尚未运行。

| 检查 | 结果 |
|---|---|
| PHOENIX 离线测试 | 35 passed |
| 两个冻结配置的 fake 演练 | 均通过 |
| OpenAI 模型访问检查 | Luna、Sol 均可访问 |
| Luna 真实调用 | 1 次，883 输入 / 103 输出 tokens，费用 $0.0001398 |
| Sol 真实调用 | 1 次，882 输入 / 39 输出 tokens，费用 $0.002154 |
| JSON / DSL / 实际 CPU 工具执行 | 两者均通过；各 11 次工具操作 |
| 截断 / 重试 / 缓存命中 | 两次均无 |
| 账本计费合计 | **$0.0022938**，按仓库 PriceBook 与 usage 计算；未查询供应商发票 |
| 原始账本与受保护配置 | 原始账本前缀保留，仅追加两行；价格和预算未修改 |
| 正常状态同步 | 两次 ledger/cache 均已提交并推送 |
| 独立审计 | 两次 PASS，原文见 research/audit_log.md |

本次使用固定合成小数据，仅执行校准模式中的各一项设计任务。验证了实际模型接入、输出解析、受限 pipeline 执行、预算与状态持久化；未验证真实 LLM 的完整恢复决策链路或恢复效果。合成验证分数不作为研究结果。两个 smoke capability_table 样本不足，不能用于生产恢复，preflight 会拒绝。

## 获取与安装

推荐从已同步的独立分支继续：
[phoenix_smoke_20261031](https://github.com/KevinChunye/AutoAgentNetwork/tree/phoenix_smoke_20261031)。main 未修改。

```bash
git fetch origin phoenix_smoke_20261031
git switch -c phoenix_recovery_work FETCH_HEAD
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,phoenix]'
python -m pytest -q tests/test_phoenix_*.py
aan status
```

Python 3.12 为本次验证版本。依赖锁在 requirements-phoenix.lock。安全配置 AAN_OPENAI_API_KEY 与 AAN_ANTHROPIC_API_KEY，不把值写入 YAML、源码或命令历史。本次密钥仅临时注入进程，未保存在交付文件。

## 后续次序

1. 验证 Anthropic 模型访问，并补全其他任务族的兼容性 smoke；本次没有调用 Anthropic。
2. 按 docs/PHOENIX.md 准备三个数据集与 18 个 checkpoint；sealed test 只留给最终 evaluator。
3. 完成三个模型各 30 项、合计 90 项的训练内部能力校准。两个 smoke 输出不参与合并。观察能力差异，不预设异构优势。
4. 冻结非合成、完整的 capability table；生成 360 个 DRAFT 分支配置。按计划准备固定 proposal pool 并冻结其来源。
5. 每个分支先 fake 演练、冻结、提交，再 aan estimate / aan check / aan run。一次只运行一个付费任务，遵守原始 governor 和账本同步流程。
6. 所有最终 predictor 冻结后，统一 seal / evaluate / report。不能边看测试集边修改方法。

完整方法、基线、指标、矩阵与局限见 docs/PHOENIX_PLAN.md；实际命令见 docs/PHOENIX.md。Formal recovery、F0/F1 对照与跨供应商效果都还未验证。预算剩余必须执行 aan status 核实，不能按 lifetime cap 推断，更不能创建空账本或修改受保护额度。

原始模型输出与 usage 见 results/phoenix_smoke_<model_ref>/calls.json；状态见同目录 status.json；受控配置位于 configs/experiments/phoenix_smoke/。付费状态提交：Luna 822889699ff5c4f833d5711d27fa6f03560a597a；Sol eec5598fd1ce4217239fbbd9a1c6edf866172ed0。
