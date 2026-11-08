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


def send_mail(subject, lines):
    smtp_user = os.environ["SMTP_USER"]
    to_addr = os.environ.get("MAIL_TO") or smtp_user
    body = "\n".join(lines) + "\n\n--\nAniCh 追番提醒（自动发送）\n"
    msg = MIMEText(body, "plain", "utf-8")
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
            updates.append("%s：第%d集 → 第%d集（共%s集）" % (
                title, old, ep, it.get("episodes_total") or "?"))
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
    for u in updates:
        print("[update] %s" % u)

    state["episodes"] = eps
    if new_subs or updates:
        state["updated"] = int(time.time())
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    if updates:
        send_mail("AniCh 追番更新 · %d 部" % len(updates),
                  ["你的收藏有新集数了：", ""] + updates)
        print("[mail] 已发送")
    return 0


if __name__ == "__main__":
    sys.exit(main())
