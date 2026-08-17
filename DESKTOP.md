# 本仓库是什么

这是本地桌面版工作树，基于 [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent)，不是官方仓。

TokenPlan 导入 **开箱即用**，门户 [https://plan.khrey.com/](https://plan.khrey.com/)。`mykey.py` 不会进 git / 不会打进安装包。

## 安装包（给别人用）

打好的包在 GitHub Releases：

https://github.com/ggandmee-cloud/GenericAgent-desktop/releases

| 文件 | 给谁 |
|------|------|
| `GenericAgent-Desktop-macOS.dmg` | macOS：打开 DMG，把 App 拖进 Applications |
| `GenericAgent-Desktop-Windows-Portable.zip` | Windows：解压后双击 `GenericAgent.exe` |
| `GenericAgent-Desktop-Linux-Portable.tar.gz` | Linux：解压后 `./GenericAgent.AppImage` |

macOS 若提示无法验证开发者：DMG 里双击 `open_anyway.command`，或右键 App → 打开。

启动后设置 / 模型菜单点 **GA Token** 即打开 plan.khrey.com，本机 34134 写入 key。

**手机互联**：设置 → **手机互联** 出示二维码（或打开 hub `/pair`）。手机 GA → 设置 → **PC 互联** → 扫码连接（载荷 `ga-pclink:v1:` + 9 位码；也可手输）。协议仍是既有 hub_p2p，不改信号服。

本机重新打 macOS DMG：

```bash
bash frontends/desktop/packaging/scripts/macos/build_dmg.sh
# 产物：artifacts/macos/out/GenericAgent-Desktop-macOS.dmg
```

CI：推送标签 `desktop-portable-*` 会打三端并挂到同一个 Release（见 `.github/workflows/desktop-release-package.yml`）。

## OTA（应用内更新）

装好的应用在 **设置 → 检查更新**：第一次点检查最新版本，发现新版本再点一次即下载 `GenericAgent-runtime.tar.gz` 覆盖运行时（Python 源码 + 前端静态资源），重启应用生效。桌面壳（Tauri 可执行文件）不通过 OTA 更新。

- 默认更新源：[plan.khrey.com/desktop/latest.json](https://plan.khrey.com/desktop/latest.json)（安装包页 [plan.khrey.com/desktop/](https://plan.khrey.com/desktop/)）
- 版本来源：仓库根 `VERSION` vs manifest `version`；有 runtime 资产且版本不同即提示更新
- 覆盖时保护用户数据：`mykey.py`、`temp/`、`memory/`、`tasks/`、`.venv/` 等永不写入（见 `frontends/desktop_ota.py` 的 `PROTECTED`）
- manifest 内联 `sha256`（或 GitHub 旁路 `.sha256` 资产）下载后校验
- 更新成功后壳层调用 `restart_runtime`：杀掉 detached hub（19736/19737）并重启 bridge，再刷新页面——**仅 `location.reload` 不够**
- 换更新源：`GA_OTA_FEED=<url>`；回落 GitHub：`GA_OTA_REPO=owner/name`
- 发新版：改 `VERSION`，推标签 `desktop-portable-<版本>`，CI 打三端并挂 Release，随后 **自动镜像**到 [plan.khrey.com/desktop/](https://plan.khrey.com/desktop/)（job `publish-plan-khrey`，脚本 `frontends/desktop/packaging/scripts/sync_plan_khrey_desktop.sh`）
- 镜像所需仓库 Secrets：`PLAN_KHREY_SSH_HOST`、`PLAN_KHREY_SSH_USER`、`PLAN_KHREY_SSH_KEY`（可选 `PLAN_KHREY_DESKTOP_DIR` / `PLAN_KHREY_PUBLIC_BASE` / `PLAN_KHREY_SSH_PORT`）

## 从源码跑

开发启动见 `frontends/desktop/`。macOS 装机说明：`docs/macos_desktop_installation_zh.md`。

换门户 / 邀请码：`GA_TOKENPLAN_URL`、`GA_TOKENPLAN_INVITE`。关掉导入：删 `plugins/subscription_portal.py` 后重启。
