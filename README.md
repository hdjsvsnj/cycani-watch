# 次元城收藏番剧更新提醒

只监控你收藏的番剧（当前：《魔法少女育成计划 restart》，video_id 3945），集数变大就发一封 QQ 邮件。

## 原理

- 站点接口 `GET /api/videos/{id}` + 请求头 `X-App-Name: cyc_web`，返回里 `remarks`（如 `05|周六25:35后`）前面的数字就是当前集数。
- 脚本每轮只发 1 个请求，和 `state.json` 里记录的旧集数比对，变大才发信。
- SMTP 走 `smtp.qq.com:465`，SSL 直连。

## 为什么不用 GitHub Actions

站点按访问 IP 地区封禁。GitHub 官方运行器在美国，实测直接返回 `HTTP 403`（页面文字是"本站无法向您提供服务"）。所以云端必须是国内 IP。

## 方案 A：手机常驻（推荐，免费且电脑关机也在跑）

条件：一部能一直插电、联网的安卓设备（手机或平板）。

1. 从 F-Droid 安装 Termux（不要用应用商店的旧版）和 Termux:Boot。
2. 打开 Termux，粘贴执行：

```
pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/hdjsvsnj/cycani-watch/main/termux-setup.sh -o s.sh && bash s.sh
```

过程中会提示粘贴一次 QQ 邮箱授权码，粘贴后回车。

3. 常驻运行：

```
cd ~/cycani && nohup ./run.sh >/dev/null 2>&1 &
```

4. 开机自启（装好 Termux:Boot 后，打开一次 App）：

```
mkdir -p ~/.termux/boot && ln -sf ~/cycani/run.sh ~/.termux/boot/cycani.sh
```

5. 关闭系统电池优化：设置 → 应用 → Termux → 电池 → 不限制。否则 Android 会杀掉后台。

巡检间隔 60 秒，日志在 `~/cycani/run.log`。

## 方案 B：国内云函数（如果你有腾讯云/阿里云账号）

服务器有国内 IP 也能跑同一份 `watch.py`，用环境变量代替 `config.json`：

```
CYCANI_SMTP_USER / CYCANI_SMTP_PASS / CYCANI_MAIL_TO
```

定时触发器设 1 分钟一次，把 `state.json` 存在函数层可写存储（或对象存储）里。

## 换番剧

改 `config.json` 里的 `watch` 数组，`id` 取 `https://www.cycani.org/anime/<数字>` 里的数字，可放多部。

## 限制

- 站点会对高频请求限流（403），脚本已带退避重试；单部番剧 60 秒一轮实测正常。
- QQ 邮箱对每日发信量有上限，一部番剧一天最多一两封，不会碰到。
