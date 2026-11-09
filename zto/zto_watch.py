#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中通快递签收提醒 · GitHub Actions 版
轮询快递100 实时查询接口，一旦签收就发邮件，并发"已提醒"标记避免重复。
"""

import hashlib
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(HERE, "delivered.json")
LOG = os.path.join(HERE, "track_cache.json")

QUERY_URL = "https://poll.kuaidi100.com/poll/query.do"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

WAYBILL = os.environ.get("ZTO_WAYBILL", "").strip()
PHONE = os.environ.get("ZTO_PHONE", "").strip()
COM = os.environ.get("ZTO_COM", "zhongtong").strip()

# 签收类关键字（中通轨迹文本）
SIGN_WORDS = ("已签收", "签收人", "本人签收", "代收", "已妥投", "已送达")


def _tz_now():
    t = time.gmtime(time.time() + 8 * 3600)
    return "%d年%d月%d日 %02d:%02d:%02d" % (
        t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def query():
    """调用快递100 实时查询（签名接口），返回接口原始 json"""
    customer = os.environ["KD100_CUSTOMER"]
    key = os.environ["KD100_KEY"]
    param = json.dumps({"com": COM, "num": WAYBILL, "phone": PHONE},
                       ensure_ascii=False, separators=(",", ":"))
    sign = hashlib.md5((param + customer + key).encode("utf-8")).hexdigest().upper()
    body = urllib.parse.urlencode({
        "customer": customer,
        "sign": sign,
        "param": param,
    }).encode("utf-8")
    req = urllib.request.Request(
        QUERY_URL, data=body,
        headers={"User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read().decode("utf-8", "replace")
            break
        except Exception as e:
            last = e
            if attempt < 2:
                print("[retry] 查询失败（%s: %s），重试" % (type(e).__name__, e))
                time.sleep(2 * (attempt + 1))
    else:
        raise last
    obj = json.loads(raw)
    return obj


def send_mail(subject, lines):
    smtp_user = os.environ["SMTP_USER"]
    to_addr = os.environ.get("MAIL_TO") or smtp_user
    plain = "\n".join(lines) + "\n\n--\n中通签收提醒（自动发送）\n"

    html_lines = "".join(
        '<p style="margin:0 0 10px 0;">%s</p>' % l if l else "<br>"
        for l in lines)
    html = ('<div style="font-family:-apple-system,Segoe UI,sans-serif;'
            'font-size:14px;color:#222;">%s'
            '<p style="color:#999;font-size:12px;margin-top:18px;">--<br>'
            '中通签收提醒（自动发送）</p></div>' % html_lines)

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("中通签收提醒", "utf-8")), smtp_user))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=25, context=ctx) as s:
        s.login(smtp_user, os.environ["SMTP_PASS"])
        s.sendmail(smtp_user, [to_addr], msg.as_string())


def main():
    if not WAYBILL:
        print("[error] 缺少 ZTO_WAYBILL")
        return 1

    if not (os.environ.get("KD100_KEY") and os.environ.get("KD100_CUSTOMER")):
        print("[skip] 还没配置快递100 的 key，跳过本轮")
        return 0

    # 已经提醒过就退出，避免重复发信
    if os.path.exists(FLAG):
        print("[skip] 该单号已提醒过，退出")
        return 0

    obj = query()
    code = str(obj.get("status") or obj.get("returnCode") or "")
    if code and code not in ("200", "0000", "0"):
        print("[warn] 接口返回异常：%s" % json.dumps(obj, ensure_ascii=False)[:300])
        return 1

    data = obj.get("data") or []
    state = str(obj.get("state") or "")
    latest = data[0] if data else {}
    ctx = str(latest.get("context") or "")
    t = str(latest.get("ftime") or latest.get("time") or "")

    print("[query] state=%s 最新轨迹：%s %s" % (state, t, ctx))

    with open(LOG, "w", encoding="utf-8") as f:
        json.dump({"time": _tz_now(), "state": state, "latest": latest},
                  f, ensure_ascii=False, indent=2)

    # 接口空壳/查无结果一律不算签收，避免假阳性误发
    if not data or "查无结果" in ctx or not ctx:
        print("[ok] 暂无有效轨迹，不判定签收")
        return 0

    delivered = (state == "3") or any(w in ctx for w in SIGN_WORDS)
    if not delivered:
        print("[ok] 尚未签收")
        return 0

    lines = [
        "欧尼酱！你的快递已经签收了：",
        "",
        "运单号：%s" % WAYBILL,
        "签收时间：%s" % (t or _tz_now()),
        "最新轨迹：%s" % ctx,
        "",
        "备注：这条提醒来自自动巡检，收到后本次任务已自动结束。",
    ]
    send_mail("快递签收提醒 · 中通 %s" % WAYBILL, lines)
    print("[mail] 签收提醒已发送")

    with open(FLAG, "w", encoding="utf-8") as f:
        json.dump({"waybill": WAYBILL, "time": _tz_now()}, f, ensure_ascii=False)

    # 顺便把工作流停掉：写完标记文件由 workflow 提交并删除定时触发
    return 0


if __name__ == "__main__":
    sys.exit(main())
