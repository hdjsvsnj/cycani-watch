# -*- coding: utf-8 -*-
"""AniCh 追番更新提醒 · GitHub Actions 版（基线存仓库文件）"""

import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate

BASE = "https://anich.sends.eu.org"
UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def _varint(n):
    out = b""
    while True:
        if n < 128:
            return out + bytes([n])
        out += bytes([(n & 0x7F) | 0x80])
        n >>= 7


def _ld(tag, val):
    b = val.encode("utf-8") if isinstance(val, str) else val
    return bytes([tag]) + _varint(len(b)) + b


def commas(raw):
    return ",".join(str(x) for x in raw)


def _read_varint(buf, i):
    v = 0
    s = 0
    n = len(buf)
    while i < n:
        x = buf[i]
        i += 1
        v |= (x & 0x7F) << s
        if not x & 0x80:
            break
        s += 7
    return v, i


def _parse(buf):
    i = 0
    out = []
    n = len(buf)
    while i < n:
        tag, i = _read_varint(buf, i)
        f, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _read_varint(buf, i)
            out.append((f, wt, v))
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            out.append((f, wt, buf[i:i + ln]))
            i += ln
        elif wt == 1:
            out.append((f, wt, buf[i:i + 8]))
            i += 8
        elif wt == 5:
            out.append((f, wt, buf[i:i + 4]))
            i += 4
        else:
            break
    return out


def auth_header(token):
    t = format(int(time.time() * 1000) + 60000, "x")
    return commas(_ld(10, token) + _ld(18, t))


def http(url, data=None, headers=None, timeout=20):
    hdr = {"User-Agent": UA}
    hdr.update(headers or {})
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else data.encode("utf-8")
        hdr.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def login_token(user, password):
    payload = commas(_ld(10, user) + _ld(18, password))
    raw = http(BASE + "/login", data="data=" + urllib.parse.quote(payload),
               headers={"Origin": "https://anich.emmmm.eu.org"})
    if raw.startswith(b"{"):
        obj = json.loads(raw.decode("utf-8", "replace"))
        raise RuntimeError("登录失败: %s" % obj.get("message"))
    for f, wt, v in _parse(raw):
        if f == 3 and wt == 2:
            for g, w2, v2 in _parse(bytes(v)):
                if g == 2 and w2 == 2:
                    return bytes(v2).decode("utf-8", "replace")
    raise RuntimeError("登录响应无法解析")


def api_get(path, token):
    raw = http(BASE + path, headers={
        "_": auth_header(token),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://anich.emmmm.eu.org"})
    obj = json.loads(raw.decode("utf-8", "replace"))
    if obj.get("error"):
        raise RuntimeError("接口错误: %s" % obj.get("message"))
    return obj.get("body") or {}


def collect_watch(token):
    items = []
    page = 1
    while page <= 20:
        body = api_get("/action/collect/watch?page=%d" % page, token)
        items.extend(body.get("data") or [])
        if not body.get("next"):
            break
        page += 1
    return items


def _tz_now():
    t = time.gmtime(time.time() + 8 * 3600)
    return "%d年%d月%d日 %02d:%02d:%02d" % (
        t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)


def _card_html(title, sub, img, extra=""):
    img_html = ('<img src="%s" width="96" style="width:96px;height:132px;object-fit:cover;'
                'border-radius:6px;display:block;" />' % img) if img else ""
    return ('<table cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px 0;">'
            '<tr><td valign="top" style="padding-right:12px;">%s</td>'
            '<td valign="top" style="font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;'
            'color:#222;line-height:1.7;">%s</td></tr></table>' % (img_html, extra or title + sub))


def send_mail(subject, lines, cards=None, intro=None):
    smtp_user = os.environ["SMTP_USER"]
    to_addr = os.environ.get("MAIL_TO") or smtp_user
    plain = "\n".join(lines) + "\n\n--\nAniCh 追番提醒（自动发送）\n"

    html_parts = ['<div style="font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;color:#222;">']
    if intro:
        html_parts.append('<p style="margin:0 0 16px 0;font-size:15px;">%s</p>' % intro)
    for c in (cards or []):
        html_parts.append(_card_html(c[0], c[1], c[2], c[3] if len(c) > 3 else ""))
    html_parts.append('<p style="color:#999;font-size:12px;margin-top:20px;">--<br>'
                      'AniCh 追番提醒（自动发送）</p></div>')
    html = "\n".join(html_parts)

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("AniCh 追番提醒", "utf-8")), smtp_user))
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=25, context=ctx) as s:
        s.login(smtp_user, os.environ["SMTP_PASS"])
        s.sendmail(smtp_user, [to_addr], msg.as_string())


def main():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    eps = state.get("episodes") or {}

    token = login_token(os.environ["ANICH_USER"], os.environ["ANICH_PASS"])
    try:
        http(BASE + "/init", headers={"_": auth_header(token)})
    except Exception:
        pass
    items = collect_watch(token)

    if not items:
        print("[warn] 收藏为空，本轮跳过")
        return 0

    updates, new_subs = [], []
    for it in items:
        vid = str(it.get("id"))
        title = it.get("title") or ("#" + vid)
        ep = int(it.get("episode") or 0)
        if vid not in eps:
            eps[vid] = ep
            new_subs.append("%s（当前第%d集）" % (title, ep))
            continue
        old = int(eps[vid])
        if ep > old:
            updates.append((it, old, ep))
            eps[vid] = ep
        elif ep < old:
            eps[vid] = ep

    print("[sync] 收藏 %d 部" % len(items))
    if os.environ.get("TEST_MAIL") == "1":
        send_mail("AniCh 测试邮件 · GitHub Actions",
                  ["这是一封测试邮件，证明云端巡检与发信链路正常。"])
        print("[mail] 测试邮件已发送")
    for s in new_subs:
        print("[new] %s" % s)
    for (it, old, ep) in updates:
        print("[update] %s：第%d集 → 第%d集" % (it.get("title"), old, ep))

    state["episodes"] = eps
    if new_subs or updates:
        state["updated"] = int(time.time())
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if updates:
        now = _tz_now()
        lines = ["欧尼酱！你收藏的番剧更新啦："]
        cards = []
        for (it, old, ep) in updates:
            name = it.get("title") or "?"
            block = ("番剧名称：%s<br>更新时间：%s<br>备注信息：第%d集" % (name, now, ep))
            lines.append("")
            lines.append("番剧名称：%s" % name)
            lines.append("更新时间：%s" % now)
            lines.append("备注信息：第%d集" % ep)
            cards.append((name, "第%d集" % ep, it.get("image"), block))
        send_mail("番剧更新提醒", lines, cards=cards,
                  intro="欧尼酱！你收藏的番剧更新啦：")
        print("[mail] 已发送")
    elif os.environ.get("FORCE_REPORT") == "1":
        now = _tz_now()
        lines = ["本次巡检结论：暂无更新。", "", "当前「我在看的」收藏："]
        cards = []
        for it in items:
            name = it.get("title") or it.get("id")
            sub = "第%s集 / 共%s集" % (it.get("episode") or "?", it.get("episodes_total") or "?")
            block = ("番剧名称：%s<br>更新时间：%s<br>备注信息：%s" % (name, now, sub))
            lines.append("- %s（%s）" % (name, sub))
            cards.append((name, sub, it.get("image"), block))
        send_mail("AniCh 巡检报告 · 暂无更新", lines, cards=cards,
                  intro="本次巡检结论：暂无更新。当前「我在看的」收藏：")
        print("[mail] 巡检报告已发送（暂无更新）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
