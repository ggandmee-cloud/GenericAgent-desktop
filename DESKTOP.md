# 本仓库是什么

这是本地桌面版工作树，基于 [lsdefine/GenericAgent](https://github.com/lsdefine/GenericAgent)，不是官方仓。

TokenPlan 导入与上游 GAnet 插件同款：**先探测本机，缺失再从 [plan.khrey.com](https://plan.khrey.com/) 安装**。`mykey.py` 不会进 git / 不会打进安装包。

## 安装包（给别人用）

打好的包在 GitHub Releases：

https://github.com/ggandmee-cloud/GenericAgent-desktop/releases

| 文件 | 给谁 |
|------|------|
| `GenericAgent-Desktop-macOS.dmg` | macOS：打开 DMG，把 App 拖进 Applications |
| `GenericAgent-Desktop-Windows-Portable.zip` | Windows：解压后双击 `GenericAgent.exe` |
| `GenericAgent-Desktop-Linux-Portable.tar.gz` | Linux：解压后 `./GenericAgent.AppImage` |

macOS 若提示无法验证开发者：DMG 里双击 `open_anyway.command`，或右键 App → 打开。

启动后设置 / 模型菜单点 **GA Token**：先探测 `plugins/subscription_portal.py`（源码树还会探测 `extras/ga-tokenplan-import`），没有则从 `https://plan.khrey.com/desktop/plugin-manifest.json` 校验安装，再打开门户，本机 34134 写入 key。

**手机互联**：设置 → **手机互联** 出示二维码（或打开 hub `/pair`）。手机 GA → 设置 → **PC 互联** → 扫码连接（载荷 `ga-pclink:v1:` + 9 位码；也可手输）。协议仍是既有 hub_p2p，不改信号服。

本机重新打 macOS DMG：

```bash
bash frontends/desktop/packaging/scripts/macos/build_dmg.sh
# 产物：artifacts/macos/out/GenericAgent-Desktop-macOS.dmg
```

CI：推送标签 `desktop-portable-*` 会打三端并挂到同一个 Release（见 `.github/workflows/desktop-release-package.yml`）。

## OTA（应用内更新）

装好的应用在 **设置 → 检查更新**（启动时也会自动检查）：

1. **运行时通道**（小包）：下载 `GenericAgent-runtime.tar.gz`，覆盖 Python/前端静态资源，保护 `mykey` / `temp` / `memory` / `tasks` 等；然后 `restart_runtime` 换掉旧 bridge/hub。
2. **壳通道**（大包）：当 `platforms.*` 的 semver **高于**当前壳版本时，下载整包到系统临时目录，用 OS-temp helper 在应用退出后换 `.app` / `.exe` / AppImage，并回灌 PROTECTED 用户数据。成功验证用 `/identity` 的新 `build_id`，不用裸「端口有应答」。

- 默认更新源：[plan.khrey.com/desktop/latest.json](https://plan.khrey.com/desktop/latest.json)
- 壳版本：`tauri.conf.json` / `Cargo.toml` / `package.json` / 根 `VERSION` 必须一致（CI job `version-lock`）；比较规则为 semver **只升不降**
- 第一版带 helper 的壳需**手动装一次**（鸡生蛋）；之后才能应用内换壳
- Translocation / 只读安装位：拒绝自动换壳，提示拖到「应用程序」后手动重装
- 发新版：改 `VERSION` 与上述三处壳版本，推标签 `desktop-portable-<版本>`，CI 打三端并自动镜像到 plan.khrey.com

详见工作区计划 `PLAN_SHELL_OTA.md`（gamobile）。

## 从源码跑

开发启动见 `frontends/desktop/`。macOS 装机说明：`docs/macos_desktop_installation_zh.md`。

换门户 / 邀请码：`GA_TOKENPLAN_URL`、`GA_TOKENPLAN_INVITE`。插件清单：`GA_TOKENPLAN_PLUGIN_MANIFEST`。关掉导入：删 `plugins/subscription_portal.py` 后重启（下次点 GA Token 会再探测并安装）。
