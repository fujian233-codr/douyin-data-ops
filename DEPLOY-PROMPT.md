# 部署提示词（复制下方整段给你的 AI）

把下面这段话完整复制给 Codex（或其他能操作本机文件的 AI），它会把这套抖音数据流水线在你的电脑上装好：

---

请帮我部署 douyin-data-ops 抖音数据复盘流水线，严格按下面的步骤执行，遇到做不到的先停下来告诉我，不要猜：

## 背景

这是一套本地抖音创作者数据流水线：通过 DouyinDataReview（开源，MIT）的官方只读 MCP 拉取我本人创作者中心数据（作品指标、流量来源、粉丝画像），配合每日 XLSX 导入，生成账号诊断报告。零第三方依赖（纯 Python 标准库），数据只存本机 SQLite，不上传任何云端。

仓库位置（二选一）：
- 优先：直接发 ZIP 包给朋友（微信/网盘均可），解压到固定目录后把路径告诉 AI。私有仓库，朋友没有 GitHub 权限时用这条路。
- 或：`https://github.com/fujian233-codr/douyin-data-ops`（已获授权的协作者克隆用；国内克隆失败时试镜像 `https://gh-proxy.com/https://github.com/fujian233-codr/douyin-data-ops`，仅公开内容可用）

没有 git 时：直接用朋友转发的 ZIP 包；拿不到 ZIP 再试镜像 `https://gh-proxy.com/https://github.com/fujian233-codr/douyin-data-ops/archive/refs/heads/main.zip`（私有仓库镜像不可用时，请仓库主人导出 ZIP 发给你）。

## 第一步：环境检查

1. 确认是 Windows。
2. 运行 `py -3 --version`，需要 Python 3.10 或更新；没有就去 python.org 装，装完继续。
3. 运行 `node --version`；没有 Node 就停下来提醒我安装 Node LTS（这一步必须人工），装完继续。
4. 确认 Codex 已安装（存在 `%USERPROFILE%\.codex\config.toml`）。

## 第二步：项目自检

1. 在仓库目录运行 `py -3 -m unittest discover -s tests -v`，全部通过才继续；有失败先修或报告给我。
2. 确认目录结构：`config/`、`scripts/`、`src/`、`data/inbox/`（没有 `data/inbox` 就创建）。

## 第二步半（可选）：独立采集器依赖

如果想用完全独立的 douyin-direct 采集器（不依赖 DouyinDataReview 应用）：运行 `py -3 -m pip install playwright` 和 `playwright install chromium`（约 150MB，仅登录环节需要；不想装就跳过，用 MCP/CSV 路径不影响）。

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

## 常见故障排查（首跑或日常使用卡住时按这条自救）

1. **「令牌对不上：应用可能换过令牌」**：让用户完全退出 DouyinDataReview（注意托盘图标也要右键退出）→ 删除 `%APPDATA%\内容数据工作台\collector\mcp-token` → 重新打开应用。应用启动会自动生成新令牌并写盘，之后重试。
2. **`creator_read` 返回里有 `"truncated": true`**：官方工具有 3 万字符响应上限。把批次减半重试；`work_list` 单页仍超限就减小 count（每页 2-3 条起步，截断就降到 1）。
3. **拉到的数据对不上 / 和历史快照 video_id 交集为 0**：先单条调用 `user_info`，核对 `nick_name` 和 `follower_count` 是不是目标账号；不是就停下，让用户在应用里切换账号后重拉，错号数据不要导入。
4. **连不上 47652 / 提示先把应用打开**：DouyinDataReview 没在运行或没登录，人工打开并登录后重试。

---

# 人工三步（AI 装完后你来做）

1. **装并登录 DouyinDataReview**（如果还没装）：从 [Releases](https://github.com/ZhangYukwiver/DouyinDataReview/releases/latest) 下载安装，打开并登录你自己的抖音账号。SmartScreen 提示时点「更多信息 → 仍要运行」。
2. **重启 Codex 会话**：新加的 MCP 要重启才会加载。
3. **首跑验证**：保持 DouyinDataReview 开着，对 AI 说「拉一次数据」。AI 会走 `creator_read` 冒烟 → 拉全量作品和流量来源 → 生成报告。之后日常复盘只需说「复盘我的抖音账号」。
