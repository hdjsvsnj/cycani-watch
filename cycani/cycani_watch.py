#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""次元城追番更新提醒（公开接口版，不需要登录）

watch 列表里的每部番，用 /api/videos/{id} 读 remarks（形如 "07|周六25:35后"），
取前面的集数；比 state.json 记录的变大就发一封邮件并更新基线，变小则静默重置。
"""
import json
import os
import re
import smtplib
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
STATE = os.path.join(HERE, "state.json")
API = "https://www.cycani.org/api"
TZ = timezone(timedelta(hours=8))
HEADERS = {
    "X-App-Name": "cyc_web",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Time-Zone": "Asia/Shanghai",
    "Referer": "https://www.cycani.org/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "Chrome/120.0 Safari/537.36",
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_video(vid):
    url = "%s/videos/%s" % (API, vid)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    if data.get("code") != 0:
        raise RuntimeError("接口返回异常: %s" % data)
    return data["data"]


def ep_of(remarks):
    """从 '07|周六25:35后' 这类文案里取集数"""
    if not remarks:
        return None
    m = re.match(r"\s*第?\s*([0-9]+(?:\.[0-9]+)?)", str(remarks))
    if not m:
        m = re.search(r"([0-9]+)", str(remarks))
    if not m:
        return None
    v = float(m.group(1))
    return int(v) if v == int(v) else v


def send_mail(subject, html, text, cfg):
    user = cfg.get("smtp_user") or os.environ.get("SMTP_USER")
    pwd = cfg.get("smtp_pass") or os.environ.get("SMTP_PASS")
    to = cfg.get("mail_to") or os.environ.get("MAIL_TO")
    if not (user and pwd and to):
        print("[warn] 邮件配置缺失，跳过发送")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((str(Header("次元城追番提醒", "utf-8")), user))
    msg["To"] = to
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=30) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    print("[mail] 已发送:", subject)
    return True


def build_mail(events):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    lines = ["欧尼酱！有番更新啦～", ""]
    rows = []
    for e in events:
        rows.append("<tr><td style='padding:6px 12px'>%s</td>"
                    "<td style='padding:6px 12px'>第 %s 话</td></tr>"
                    % (e["title"], e["ep"]))
        lines.append("· 《%s》更新到第 %s 话" % (e["title"], e["ep"]))
    lines += ["", "巡检时间：%s" % now]
    html = ("<div style='font-family:-apple-system,Segoe UI,sans-serif'>"
            "<p>欧尼酱！有番更新啦～</p>"
            "<table style='border-collapse:collapse;border:1px solid #eee'>"
            "<tr style='background:#fafafa'><th style='padding:6px 12px;text-align:left'>番剧</th>"
            "<th style='padding:6px 12px;text-align:left'>进度</th></tr>%s</table>"
            "<p style='color:#888;font-size:12px'>巡检时间：%s</p></div>" % ("".join(rows), now))
    subject = "次元城更新：" + "；".join("《%s》第%s话" % (e["title"], e["ep"]) for e in events)
    return subject, html, "\n".join(lines)


def main():
    cfg = load_json(CONFIG, {})
    watch = cfg.get("watch") or []
    if not watch:
        print("[warn] config.json 里 watch 为空")
        return 1
    state = load_json(STATE, {})
    events, problems = [], []
    for item in watch:
        vid, title = str(item["id"]), item.get("title") or str(item["id"])
        try:
            data = get_video(vid)
        except Exception as exc:
            problems.append("%s(%s) 读取失败: %s" % (title, vid, exc))
            print("[warn] %s 读取失败: %s" % (title, exc))
            continue
        remarks = data.get("remarks") or ""
        ep = ep_of(remarks)
        if ep is None:
            problems.append("%s 无法解析集数: %r" % (title, remarks))
            print("[warn] %s remarks=%r 无法解析" % (title, remarks))
            continue
        old = state.get(vid)
        if old is None:
            print("[init] %s(%s) 基线=%s (%s)" % (title, vid, ep, remarks))
        elif ep > old:
            events.append({"title": title, "ep": ep, "old": old})
            print("[new] %s(%s) %s -> %s" % (title, vid, old, ep))
        elif ep < old:
            print("[reset] %s(%s) %s -> %s 静默重置" % (title, vid, old, ep))
        else:
            print("[ok] %s 无更新 (%s)" % (title, ep))
        state[vid] = ep
    save_json(STATE, state)
    if events:
        subject, html, text = build_mail(events)
        send_mail(subject, html, text, cfg)
    if problems:
        print("[summary] 异常 %d 项" % len(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
