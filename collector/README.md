# douyin-direct 采集器（完全独立模式）

自带扫码登录、直连抖音创作者中心官方只读接口的数据采集器，不依赖 DouyinDataReview 应用，没有 MCP 令牌 / 3 万字符截断 / 账号混淆问题。

## 用法

```powershell
# 一次性安装（仅登录需要 Playwright；拉数本身零依赖）
py -3 -m pip install playwright
playwright install chromium

# 扫码登录（弹浏览器，用抖音 App 扫；会话存 data/session.json）
py -3 collector\login.py

# 全量拉取（身份核验 → 总览 → 作品 → 深挖 → 写 direct-*.json 到 inbox）
py -3 collector\pull.py --expect-nickname "<你的昵称>"

# 入库出报告（现有流水线）
py -3 scripts\import_data.py --inbox data\inbox --account main
py -3 scripts\generate_report.py --account main --latest
```

## 工作原理

扫码登录后保存账号自己的 Cookie + 浏览器身份头（`data/session.json`，权限 0600）。拉数时用这套凭据直接调用 `creator.douyin.com` 的官方网页接口——与网页版创作者中心「看数据」时浏览器发的是同一批请求。这些接口**不需要签名**（无需 a_bogus），只认 Cookie + referer。

接口白名单（9 个只读 key）与错误语义移植自 [ZhangYukwiver/DouyinDataReview](https://github.com/ZhangYukwiver/DouyinDataReview)（MIT License）的 `collector/creatorCenter.mjs` / `directApi.mjs`，在此致谢。

## 强制身份核验

`pull.py` 第 0 步永远先读 `user_info` 打印昵称/粉丝数/抖音号；提供 `--expect-nickname` 时不符即停。**每次拉数都看一眼这行输出**，防止拉错账号（真实教训）。

## 安全边界（硬约束）

- 仅本人账号、仅本机运行；`data/session.json` 绝不进 Git、绝不上传（`data/` 已在 `.gitignore`）。
- 仅白名单只读接口；本模块没有任何写操作入口。
- 请求节流 ≥0.35 秒；`login_required` / `rate_limited` / `platform_rejected` 一律立即停止，不重试轰炸。
- 只打 `creator.douyin.com`，不碰 `www.douyin.com` 接口（那批需要签名，属另一套体系）。

## 已知代价

抖音改版时接口字段可能变化，维护责任在本项目（方案 A 的选择）。失败模式参考 DouyinDataReview 同款：`status_code != 0`、HTTP 401/403（重登）、429（限流，停）。
