#!/data/data/com.termux/files/usr/bin/bash
# 安卓 Termux 一键安装：自动同步次元城账号收藏，新集发 QQ 邮件
set -e
echo "== 安装依赖 =="
pkg update -y >/dev/null 2>&1 || true
pkg install -y python curl >/dev/null 2>&1 || true

mkdir -p "$HOME/cycani"
cd "$HOME/cycani"

echo "== 下载脚本 =="
curl -fsSL https://raw.githubusercontent.com/hdjsvsnj/cycani-watch/main/watch.py -o watch.py

echo "== 填写账号 =="
read -rp "次元城账号（手机号或邮箱）: " user
read -rsp "次元城密码: " pass
echo
read -rsp "QQ 邮箱 16 位授权码: " smtp

printf '{\n  "smtp_host": "smtp.qq.com",\n  "smtp_port": 465,\n  "smtp_user": "1250712498@qq.com",\n  "mail_to": "1250712498@qq.com",\n  "account": {"username": "", "password": ""},\n  "watch": []\n}\n' > config.json

python3 - "$user" "$pass" "$smtp" <<'PY'
import json, sys
cfg = json.load(open('config.json', encoding='utf-8'))
cfg['account']['username'] = sys.argv[1].strip()
cfg['account']['password'] = sys.argv[2].strip()
cfg['smtp_pass'] = sys.argv[3].strip()
json.dump(cfg, open('config.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('账号与授权码已写入 config.json')
PY
chmod 600 config.json

echo "== 校验登录并建立基线 =="
python3 watch.py --init

cat > run.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null || true
cd "$HOME/cycani"
while true; do
  python3 watch.py >> run.log 2>&1
  sleep 60
done
EOF
chmod +x run.sh

echo
echo "== 完成 =="
echo "后台常驻：nohup ./run.sh >/dev/null 2>&1 &"
echo "开机自启：装 Termux:Boot 后 mkdir -p ~/.termux/boot && ln -sf ~/cycani/run.sh ~/.termux/boot/cycani.sh"
