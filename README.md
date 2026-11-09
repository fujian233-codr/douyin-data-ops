# 抖音创作者数据采集与复盘流水线

本项目把 [DouyinDataReview](https://github.com/ZhangYukwiver/DouyinDataReview) 导出的本人抖音创作者中心 CSV，转换成可追溯的 SQLite 快照，并生成账号、作品、题材与诊断报告。第一版只使用 Python 标准库，不接触 Cookie、登录态或第三方云端服务。

核心设计：

- 原始 CSV 按 SHA-256 去重后归档，重复导入不产生新快照。
- 标准指标与原始字段分层保存，缺失值保持 `NULL`，不用 0 猜测。
- 报告同时输出 Markdown 和 JSON，供人和 AI 复盘使用。

## 数据获取

1. 从 [DouyinDataReview Releases](https://github.com/ZhangYukwiver/DouyinDataReview/releases/latest) 下载 Windows 安装包，建议 v1.43.0 或更新版本。
2. 由账号本人安装、打开并登录；本项目的助手和脚本不得代启动、不得读取软件数据目录、不得接触 Cookie。
3. 在「创作者中心 → 作品管理」导出作品数据 CSV。
4. 如后台可见，在「数据中心 → 粉丝画像」导出画像 CSV。
5. 将 CSV 放入：

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

报告包含数据覆盖、账号总览、最新作品、题材模式、诊断结论、skill 反馈和导入问题。播放低于 500 的作品会标记为「小基数」，只观察，不做深度归因。

## 常见缺失字段

`DouyinDataReview` 的作品导出可能不包含全部深层数据。第一版最常见缺口：

- 5 秒完播率
- 曝光量
- 平均播放时长
- 涨粉量
- 单条视频流量来源

缺失字段会保持 `NULL`，报告会显式标注，不会伪造结论。

## douyin-mcp 触发条件

满足以下任一条件时，再评估接入 [douyin-mcp](https://github.com/Kuhakucai/douyin-mcp)：

- DouyinDataReview 连续两次导出成功；
- 作品 CSV 缺少 5 秒完播率、平均播放时长、曝光量、涨粉量中的任意两项。

验收标准：

- 两侧播放量误差为 0；
- `video_id` 匹配率 100%；
- `douyin-mcp` 至少补齐两个核心字段。

在满足上述条件前，不把 `douyin-mcp` 加入常规依赖。

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

