# extras

随仓带的可选件。桌面安装包**不打进**本目录；TokenPlan 导入在运行时先探测，缺失再从 plan.khrey.com 安装。

| 目录 | 作用 | 别人怎么拿 |
|------|------|------------|
| [`ga-tokenplan-import/`](ga-tokenplan-import/) | TokenPlan 本机导入 key（门户 [plan.khrey.com](https://plan.khrey.com/)，回调 34134） | 源码树启动会探测本目录；安装包点击 GA Token 时按清单下载到 `plugins/subscription_portal.py` |

关掉：删 `plugins/subscription_portal.py` 后重启（下次点击会再探测并安装）。
