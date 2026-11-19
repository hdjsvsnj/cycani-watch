# 阿里云函数计算部署

函数名 `cycani-watch`，地域 `cn-hangzhou`，运行时 `python3.10`，入口 `index.main_handler`，内存 128MB，超时 30 秒。
定时触发器 `every-1min`，cron：`CRON_TZ=Asia/Shanghai 0 * * * * *`。

## 环境变量

CYCANI_USER / CYCANI_PASS、SMTP_USER / SMTP_PASS / MAIL_TO、
GH_TOKEN / GH_REPO=hdjsvsnj/cycani-watch / GH_PATH=cycani/state.json

## 基线

云函数无本地持久盘，集数基线存在仓库 `cycani/state.json`；有变化才写回（不会每分钟提交）。
`videos._last_mail` 记录上一次发信结果，用于排查发信失败。

## 出口 IP

阿里云杭州机房出口在国内，可正常访问次元城；美国 IP（GitHub Actions）会被 403「不提供服务」。
