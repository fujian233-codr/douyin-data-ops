# 抖音创作者数据采集与复盘流水线

本项目把本人抖音创作者中心数据（首选 DouyinDataReview 内置 MCP 自动拉取，CSV 手动导出作兜底）转换成可追溯的 SQLite 快照，并生成账号、作品、题材、流量来源与诊断报告。只使用 Python 标准库，不接触 Cookie、登录态或第三方云端服务。

核心设计：

- 原始 CSV 按 SHA-256 去重后归档，重复导入不产生新快照。
- MCP 快照（JSON）与 CSV 共用同一套去重、快照与报告机制。
- 标准指标与原始字段分层保存，缺失值保持 `NULL`，不用 0 猜测。
- 报告同时输出 Markdown 和 JSON，供人和 AI 复盘使用。

## 数据获取（首选）：DouyinDataReview 内置 MCP

DouyinDataReview v1.43.0 自带官方 MCP（仅本机回环 + 令牌认证，创作者中心接口为只读白名单）。接入 Codex 后可由 AI 直接调用 `creator_read` 拉数，补齐 CSV 拿不到的流量来源、逐日趋势等字段。

一次性配置（`C:\Users\符健\.codex\config.toml`）：

```toml
[mcp_servers.douyin-review]
command = "node"
args = ["C:\\Users\\符健\\AppData\\Local\\Programs\\DouyinDataReview\\resources\\app.asar.unpacked\\collector\\mcpStdio.mjs"]
```

配置后重启 Codex 会话。拉数流程：

1. 用户本人打开 DouyinDataReview 并登录创作者中心（应用必须保持运行）。
2. AI 分批调用 `creator_read`（每批 ≤24 查询）：`dashboard`、`dashboard_fans`、`fans_summary`、`work_list`（翻页拉全量）、对最新 20 条有指标作品拉 `item_play_source` / `item_trend` / `item_summarize`。
3. 原始响应写成 `data/inbox/mcp-YYYYMMDD-HHMM.json`，结构见 SKILL.md。
4. 执行下方导入与报告命令，JSON 与 CSV 会被一起识别。

安全边界：只允许 `creator_read` 只读工具；应用由用户本人打开登录；AI 不代启动、不读 Cookie、不复制令牌文件；`login_required` 时提示用户在应用内重新登录。

## 数据获取（兜底）：CSV 手动导出

1. 从 [DouyinDataReview Releases](https://github.com/ZhangYukwiver/DouyinDataReview/releases/latest) 下载 Windows 安装包，建议 v1.43.0 或更新版本。
2. 由账号本人安装、打开并登录；本项目的助手和脚本不得代启动、不得读取软件数据目录、不得接触 Cookie。
3. 在「创作者中心 → 作品管理」导出作品数据 CSV；如后台可见，在「数据中心 → 粉丝画像」导出画像 CSV。
4. 将 CSV 放入：

```text
C:\Users\符健\Desktop\workflow\douyin-data-ops\data\inbox\
```

推荐文件名：

```text
works-YYYYMMDD-HHMM.csv
fans-YYYYMMDD-HHMM.csv
```

文件名中的时间会作为快照采集时间；没有时间时退回文件修改时间。

## 导入

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location -LiteralPath "C:\Users\符健\Desktop\workflow\douyin-data-ops"
py -3 scripts\import_data.py --inbox data\inbox --account main
```

命令输出 JSON，包含：

- 每个文件是否导入；
- 快照 ID；
- 作品或画像行数；
- 字段覆盖率；
- 缺失字段；
- 跳过原因和导入问题。

重复运行是安全的：同一文件按 SHA-256 去重，不会产生重复快照。

## 生成报告

使用最新作品快照：

```powershell
py -3 scripts\generate_report.py --account main --latest
```

指定快照：

```powershell
py -3 scripts\generate_report.py --account main --snapshot works-xxxxxxxxxxxxxxxxxxxx
```

输出：

```text
reports\snapshot-<snapshot_id>.md
reports\snapshot-<snapshot_id>.json
```

报告包含数据覆盖、账号总览、最新作品、题材模式、流量来源结构（MCP 数据才有）、诊断结论、skill 反馈和导入问题。播放低于 500 的作品会标记为「小基数」，只观察，不做深度归因。

## 常见缺失字段

`DouyinDataReview` 的作品导出可能不包含全部深层数据。第一版最常见缺口：

- 5 秒完播率
- 曝光量
- 平均播放时长
- 涨粉量
- 单条视频流量来源

缺失字段会保持 `NULL`，报告会显式标注，不会伪造结论。

## MCP 数据一致性验收

- MCP `work_list` 与最近一次 CSV 快照对比：`video_id` 匹配率 100%，播放量误差为 0；
- `item_play_source` 能产出作品级流量来源，账号级加权占比可复算；
- 单条 `user_info` 冒烟查询返回 `ok: true`。

## 测试

```powershell
py -3 -m unittest discover -s tests -v
```

## 隐私边界

- 只处理本人账号导出的数据。
- 不上传账号数据到第三方服务。
- 不采集他人账号后台数据。
- 不保存 Cookie、Token、登录态或密码。
- `data/` 与 `reports/` 已加入 `.gitignore`，不得提交。

