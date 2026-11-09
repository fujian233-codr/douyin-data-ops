# 部署提示词（复制下方整段给你的 AI）

把下面这段话完整复制给 Codex（或其他能操作本机文件的 AI），它会把这套抖音数据流水线在你的电脑上装好：

---

请帮我部署 douyin-data-ops 抖音数据复盘流水线，严格按下面的步骤执行，遇到做不到的先停下来告诉我，不要猜：

## 背景

这是一套本地抖音创作者数据流水线：通过 DouyinDataReview（开源，MIT）的官方只读 MCP 拉取我本人创作者中心数据（作品指标、流量来源、粉丝画像），配合每日 XLSX 导入，生成账号诊断报告。零第三方依赖（纯 Python 标准库），数据只存本机 SQLite，不上传任何云端。

仓库位置：<告诉你的 AI 仓库地址，或 ZIP 解压到了哪里>

## 第一步：环境检查

1. 确认是 Windows。
2. 运行 `py -3 --version`，需要 Python 3.10 或更新；没有就去 python.org 装，装完继续。
3. 运行 `node --version`；没有 Node 就停下来提醒我安装 Node LTS（这一步必须人工），装完继续。
4. 确认 Codex 已安装（存在 `%USERPROFILE%\.codex\config.toml`）。

## 第二步：项目自检

1. 在仓库目录运行 `py -3 -m unittest discover -s tests -v`，全部通过才继续；有失败先修或报告给我。
2. 确认目录结构：`config/`、`scripts/`、`src/`、`data/inbox/`（没有 `data/inbox` 就创建）。

## 第三步：探测 DouyinDataReview 并配置 MCP

1. 依次检查这些路径，找到第一个存在的 `mcpStdio.mjs`：
   - `%LOCALAPPDATA%\Programs\DouyinDataReview\resources\app.asar.unpacked\collector\mcpStdio.mjs`
   - `%PROGRAMFILES%\DouyinDataReview\resources\app.asar.unpacked\collector\mcpStdio.mjs`
   - `%LOCALAPPDATA%\Local\Programs\DouyinDataReview\resources\app.asar.unpacked\collector\mcpStdio.mjs`
2. 都不存在时，在 `%LOCALAPPDATA%\Programs` 和 `%PROGRAMFILES%` 下搜索 `DouyinDataReview` 目录；仍找不到就问我装在哪里；我说没装就提醒我去 <https://github.com/ZhangYukwiver/DouyinDataReview/releases/latest> 下载安装（人工步骤）。
3. 备份 `%USERPROFILE%\.codex\config.toml` 为 `config.toml.bak-<日期>`。
4. 检查 config.toml 里是否已有 `[mcp_servers.douyin-review]`；没有就追加（路径里的反斜杠要写成 `\\`）：

```toml
[mcp_servers.douyin-review]
command = "node"
args = ["<探测到的 mcpStdio.mjs 完整路径>"]
```

## 第四步：安装 Skill

1. 把仓库里的 `skills/douyin-data-ops/` 整个目录复制到 `%USERPROFILE%\.codex\skills\douyin-data-ops\`（已存在就先看差异再覆盖）。

## 第五步：输出结果清单

完成后告诉我：

- Python / Node 版本
- 测试是否全绿
- DouyinDataReview 路径与 MCP 配置是否写入
- Skill 是否安装
- 下一步我要做的三件人工事项

## 安全边界（必须遵守）

- MCP 只允许调用 `creator_read` 只读工具；`send_chat_message`、`douyin_interact`、`download_video`、`switch_account` 等一律禁用。
- 只处理我本人账号的数据；不读 Cookie、不复制令牌文件、不碰 DouyinDataReview 数据目录。
- 不把任何账号数据上传到第三方服务。
- 不自动操作创作者中心页面。

---

# 人工三步（AI 装完后你来做）

1. **装并登录 DouyinDataReview**（如果还没装）：从 [Releases](https://github.com/ZhangYukwiver/DouyinDataReview/releases/latest) 下载安装，打开并登录你自己的抖音账号。SmartScreen 提示时点「更多信息 → 仍要运行」。
2. **重启 Codex 会话**：新加的 MCP 要重启才会加载。
3. **首跑验证**：保持 DouyinDataReview 开着，对 AI 说「拉一次数据」。AI 会走 `creator_read` 冒烟 → 拉全量作品和流量来源 → 生成报告。之后日常复盘只需说「复盘我的抖音账号」。
