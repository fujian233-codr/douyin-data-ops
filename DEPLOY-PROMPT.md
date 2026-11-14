# 部署提示词（复制下方整段给你的 AI）

把下面分割线之间的整段话复制给 Codex（或其他能操作本机文件的 AI），它会把这套抖音数据流水线在你的电脑上装好。

---

请帮我部署 douyin-data-ops 抖音数据复盘流水线，严格按下面的步骤执行，遇到做不到的先停下来告诉我，不要猜：

## 背景

这是一套本地抖音创作者数据流水线：扫码登录自己的抖音账号 → 只读拉取本人创作者中心数据（作品指标、流量来源、逐日趋势、粉丝概况）→ 本地 SQLite 快照 → 生成账号诊断报告（含环比、流量来源结构、每日趋势）。数据只存本机，不上传任何云端。主路径是自带的 douyin-direct 独立采集器（不用装其他应用）；DouyinDataReview MCP / CSV / XLSX 是备用路径。

仓库位置（二选一）：
- 克隆：`https://github.com/fujian233-codr/douyin-data-ops`（直连失败时用镜像 `https://gh-proxy.com/https://github.com/fujian233-codr/douyin-data-ops`）
- 或：我已把仓库 ZIP 解压到 `<把解压路径写在这里>`（没有 git 时可下载 `https://gh-proxy.com/https://github.com/fujian233-codr/douyin-data-ops/archive/refs/heads/main.zip` 解压）

## 第一步：环境检查

1. 确认是 Windows。
2. 运行 `py -3 --version`，需要 Python 3.10 或更新；没有就提醒我去 python.org 安装（人工），装完继续。

## 第二步：项目自检

1. 在仓库目录运行 `py -3 -m unittest discover -s tests -v`，全部通过才继续；有失败先停下来报告，不要自行改代码。
2. 确认目录结构：`config/`、`scripts/`、`src/`、`collector/`、`data/inbox/`（没有 `data/inbox` 就创建）。

## 第三步：安装独立采集器依赖（主路径）

1. 运行 `py -3 -m pip install playwright`。
2. 运行 `py -3 -m playwright install chromium`（约 150MB，仅扫码登录环节需要；下载慢可设环境变量 `PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright` 后重试）。

## 第四步：安装 Skill

1. 把仓库里的 `skills/douyin-data-ops/` 整个目录复制到 `%USERPROFILE%\.codex\skills\douyin-data-ops\`（已存在就先给我看差异再覆盖）。

## 第五步：输出结果清单

完成后告诉我：Python 版本、测试是否全绿、Playwright 是否装好、Skill 是否安装、下一步我要做的人工事项。

## 安全边界（必须遵守）

- 只处理我本人账号的数据；采集器是只读白名单接口，没有任何写操作入口。
- 登录会话文件 `data/session.json` 只在本机（权限 0600），绝不进 Git、绝不上传、绝不外发。
- 不把任何账号数据上传到第三方服务。
- 不自动操作创作者中心页面。
- 每次拉数第 0 步都会打印账号昵称/粉丝数，必须给我看一眼确认是目标账号才能继续入库。

## 常见故障排查（首跑或日常卡住时按这条自救）

1. **登录失效（`login_required`）**：重新运行 `py -3 collector\login.py` 扫码即可。
2. **限流（`rate_limited`）**：立即停止，当天不要再拉。
3. **拉到的账号不对 / 数据和历史对不上**：看身份核验输出的昵称和粉丝数；不是目标账号就停，删掉本次快照文件，确认账号后重拉。
4. **接口报错（`platform_rejected` / `schema_changed`）**：抖音改版了，把报错原文发给仓库主人，不要自己猜着改。

---

# 人工三步（AI 装完后你来做）

1. **扫码登录**：对 AI 说「帮我登录抖音采集器」，它会运行 `py -3 collector\login.py` 弹出浏览器，用你自己的抖音 App 扫码，窗口自动关闭即完成（会打印账号昵称和粉丝数，看一眼确认）。
2. **重启 Codex 会话**：新装的 skill 要重启才会加载（只用独立采集器的话跳过也行）。
3. **首跑验证**：对 AI 说「拉一次数据」。它会走「身份核验 → 全量作品 + 流量来源 + 趋势 → 入库 → 报告」。之后日常复盘只需说「复盘我的抖音账号」。

> **备用路径**：DouyinDataReview 应用（MCP 模式）和 CSV/XLSX 手动导入仍然支持，但独立采集器完全不需要它们。想启用 MCP 备用的，安装 DouyinDataReview 后让 AI 把其 `mcpStdio.mjs` 路径写进 `%USERPROFILE%\.codex\config.toml` 的 `[mcp_servers.douyin-review]` 段并重启会话。
