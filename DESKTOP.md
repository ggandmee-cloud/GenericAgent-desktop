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

本机重新打 macOS DMG：

```bash
bash frontends/desktop/packaging/scripts/macos/build_dmg.sh
# 产物：artifacts/macos/out/GenericAgent-Desktop-macOS.dmg
```

CI：推送标签 `desktop-portable-*` 会打三端并挂到同一个 Release（见 `.github/workflows/desktop-release-package.yml`）。

## 从源码跑

开发启动见 `frontends/desktop/`。macOS 装机说明：`docs/macos_desktop_installation_zh.md`。

换门户 / 邀请码：`GA_TOKENPLAN_URL`、`GA_TOKENPLAN_INVITE`。关掉导入：删 `plugins/subscription_portal.py` 后重启。
