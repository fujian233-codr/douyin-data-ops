---
name: douyin-data-ops
description: Use when 用户要导入本人抖音创作者中心数据（MCP 拉取、每日 XLSX 或 CSV 导出）、复盘抖音账号、分析作品表现、生成数据报告，或处理 DouyinDataReview；不用于抓取他人账号或自动登录创作者中心。
---

# 抖音数据导入与复盘

## 目标

把用户本人的抖音创作者中心数据（优先走 DouyinDataReview 内置 MCP 自动拉取，每日 XLSX 与 CSV 导出作补充）变成可追溯快照，并生成可给人和 AI 使用的账号诊断报告，重点覆盖流量来源、每日趋势与跨快照环比。

## 固定位置

```text
项目：<仓库根>
输入：<仓库根>/data/inbox
报告：<仓库根>/reports
```

## 硬边界

- 只处理用户本人账号的数据。
- `DouyinDataReview` 必须由用户本人安装、打开、登录；助手不得代启动，不得读取软件数据目录（MCP 令牌文件由官方 mcpStdio 桥自行读取）。
- MCP 只允许调用只读工具 `creator_read`；工具列表中的 `send_chat_message`、`douyin_interact`、`download_video`、`switch_account` 等写操作一律禁用。
- 不接触 Cookie、Token、密码或登录态。
- 不把账号数据上传到第三方服务。
- 不抓取他人账号后台数据。

## 首选流程：MCP 自动拉取（需要 Codex 已接入 douyin-review MCP 并重启过会话）

1. 确认用户已打开 DouyinDataReview 且创作者中心为登录态（应用必须保持运行，MCP 才连得上）。
2. 分批调用 `creator_read`（每批 ≤24 个查询，批次间温和间隔）：
   - 账号总览：`dashboard`（recent_days 7/30）、`dashboard_fans`、`fans_summary`
   - 作品全量：`work_list`（status=0, count=40, 按 max_cursor 翻页直到 has_more=false）
   - 重点作品深挖（最新 20 条有指标作品）：`item_play_source`（item_id）、`item_trend`、`item_summarize`
3. 把全部原始响应写成快照 `data/inbox/mcp-YYYYMMDD-HHMM.json`，结构固定：

```json
{
  "source": "douyin-review-mcp",
  "collected_at": "<ISO 时间>",
  "queries": {
    "work_list": [<每页原始响应>],
    "item_play_source": [{"item_id": "<id>", "response": <原始响应>}],
    "item_trend": [{"item_id": "<id>", "response": <原始响应>}],
    "fans_summary": [{"response": <原始响应>}]
  }
}
```

4. 在项目目录执行导入与报告（同下方命令），JSON 会和 CSV/XLSX 一起被识别。
5. `login_required` → 提示用户在应用内重新登录；连接拒绝 → 提示用户打开 DouyinDataReview。

## 补充流程：每日账号级 XLSX（5 秒完播率等账号级指标的唯一来源）

1. 提示用户从抖音创作者中心「数据中心 → 数据表现」导出：
   - 「短视频全量指标」XLSX（播放/互动/5s完播/2s跳出/封面点击/平均播放时长）
   - 「粉丝全量指标」XLSX（总粉丝/净增/吸粉/脱粉/回访）
2. 文件直接放入 `data/inbox/`，命名建议 `daily-video-YYYYMMDD-HHMM.xlsx`、`daily-fans-YYYYMMDD-HHMM.xlsx`。
3. 跑导入命令即可；导出内容是账号级每日数据，与作品级快照互补。

## 兜底流程：CSV 手动导出

1. 提示用户：打开 DouyinDataReview →「创作者中心 → 作品管理」导出作品数据；「数据中心 → 粉丝画像」导出画像，放入 `data/inbox/`。
2. 用户放好文件后，在项目目录执行：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
py -3 scripts\import_data.py --inbox data\inbox --account main
```

3. 读取 JSON 输出，检查：`imported`、`row_count`、`missing_fields`、`issue_count` 和 `skip_reason`。
4. 有作品快照后生成报告：

```powershell
py -3 scripts\generate_report.py --account main --latest
```

5. 打开生成的 Markdown 报告，用以下顺序复盘：
   - 数据覆盖：先确认缺什么，不越过缺口下结论；
   - 账号总览：播放中位数、完播、2 秒跳出；
   - 每日趋势：账号级 5s 完播、2s 跳出、平均播放时长、粉丝净增（XLSX 数据）；
   - 作品表现：小基数和缺失字段标记；
   - 题材模式：播放、完播、互动、涨粉；
   - 环比：平均播放变化、涨跌幅前五、新增作品（第二个快照起自动生成）；
   - 流量来源：推荐/搜索/关注/主页占比，作品级来源明细（MCP 数据才有）；
   - 诊断结论：区分已证实、初步判断、小基数观察、数据缺口；
   - skill 反馈：提炼应更新到运营、叙事、选题雷达的经验。

## 判断规则

- 播放量低于 500：标记「小基数」，只观察，不做深度归因。
- 账号级 5s 完播率低于 50%：优先检查开头钩子与信息密度（每日趋势均值）。
- 2 秒跳出率达到预警线：优先检查开头钩子。
- 5 秒留存达标但整体完播偏低：优先检查中段结构和节奏。
- 完播尚可但播放偏低：检查选题、标题、封面和分发场景。
- 完播高但互动低：检查结尾引导和评论钩子。
- 推荐页流量占比低于 50%：分发规模受限是播放回落的主要解释之一。

## 失败处理

- `duplicate_sha256`：正常跳过，不是错误。
- `unrecognized_csv`：查看表头，更新 `config/field_aliases.json`，不要改原始 CSV。
- `unrecognized_json` / `invalid_json`：检查快照是否为 `douyin-review-mcp` 格式，不要手工改原始响应。
- `unrecognized_xlsx` / `invalid_xlsx` / `no_valid_daily_rows`：确认是创作者中心「数据表现」导出的原始 XLSX，不要手工编辑。
- `invalid_rate` / `invalid_count`：查看 `import_issues`，保留 NULL，不要手工猜值。
- 无快照：先完成作品数据导入，再生成报告。
- 测试命令：

```powershell
py -3 -m unittest discover -s tests -v
```

## MCP 接入配置（一次性，已配置则跳过）

`<用户目录>/.codex/config.toml` 中应有（路径按本机 DouyinDataReview 安装位置调整）：

```toml
[mcp_servers.douyin-review]
command = "node"
args = ["<DouyinDataReview 安装目录>\\resources\\app.asar.unpacked\\collector\\mcpStdio.mjs"]
```

配置后需重启 Codex 会话。验收标准：`creator_read` 单条 `user_info` 查询返回 `ok: true`；MCP 拉取的最近作品与 CSV 快照对比 `video_id` 匹配率 100%、播放量误差为 0。
