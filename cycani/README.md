# 次元城追番提醒（公开接口版）

不需要登录站点，也不需要 Cookie。靠公开接口读集数，比基线大就发一封邮件。

- 接口：`GET https://www.cycani.org/api/videos/{id}`
- 必需请求头：`X-App-Name: cyc_web`、浏览器 UA、`Referer: https://www.cycani.org/`
- 集数来源：`data.remarks` 前缀数字（如 `07|周六25:35后`）
- 找 id：`GET /api/videos/search?q=<番名>`

## 用法

```
cp config.example.json config.json   # 填 SMTP 授权码与收件箱
python3 cycani_watch.py              # 首跑只建基线，不发送
```

`state.json` 记录每部番的集数基线；集数变大发邮件，变小静默重置（换季或更换字幕组的情况）。

## 定时

cron 示例（每 10 分钟）：

```
*/10 * * * * cd /path/to/cycani && /opt/python3.12/bin/python3 cycani_watch.py >> run.log 2>&1
```

注意：站点按出口 IP 地区限制，美国 IP 会被 403「不提供服务」，所以 GitHub Actions 运行器不可用，必须在国内 IP 的机器上跑。
