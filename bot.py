import os, re, json, zipfile, shutil, logging
from tempfile import mkdtemp
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ========== GANTI INI ==========
TOKEN = "TOKEN_DARI_BOTFATHER"   # ganti dengan token asli
ADMIN_ID = 123456789             # ganti dengan ID Telegram kamu (cek di @userinfobot)
# ================================

MAX_FILE_SIZE = 200 * 1024 * 1024
DB_FILE = "users.json"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def load_users():
    if not os.path.exists(DB_FILE): return {}
    with open(DB_FILE, 'r') as f: return json.load(f)

def save_users(users):
    with open(DB_FILE, 'w') as f: json.dump(users, f, indent=2)

def is_premium(user_id):
    return load_users().get(str(user_id), {}).get("premium", False)

def get_credit(user_id):
    return load_users().get(str(user_id), {}).get("credit", 0)

def deduct_credit(user_id):
    users = load_users()
    uid = str(user_id)
    if users.get(uid, {}).get("premium"): return True
    credit = users.get(uid, {}).get("credit", 0)
    if credit > 0:
        users[uid]["credit"] = credit - 1
        save_users(users)
        return True
    return False

def replace_domain_port_in_file(file_path, old_domain, new_domain, old_port, new_port):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    changed = False
    if old_domain and new_domain and old_domain in content:
        content = content.replace(old_domain, new_domain)
        changed = True
    if old_port and new_port and old_port != new_port:
        pattern = r'(:|port\s*[:=]\s*)' + str(old_port)
        if re.search(pattern, content):
            content = re.sub(pattern, r'\1' + str(new_port), content)
            changed = True
    if changed:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    return changed

def process_zip(zip_path, old_domain, new_domain, old_port, new_port):
    temp_dir = mkdtemp()
    extract_dir = os.path.join(temp_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_dir)
    dart_files = list(Path(extract_dir).rglob("*.dart"))
    if not dart_files:
        raise Exception("Tidak ada file .dart")
    modified = 0
    for f in dart_files:
        if replace_domain_port_in_file(str(f), old_domain, new_domain, old_port, new_port):
            modified += 1
    if modified == 0:
        raise Exception("Tidak ada perubahan")
    out_zip = os.path.join(temp_dir, "modified.zip")
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(extract_dir):
            for file in files:
                full = os.path.join(root, file)
                zf.write(full, os.path.relpath(full, extract_dir))
    return out_zip, modified

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    status = "✅ Premium" if is_premium(uid) else f"🟡 Credit: {get_credit(uid)}"
    await update.message.reply_text(f"Halo JURAGAN!\nStatus: {status}\n\n/rename – Mulai rename APK")

async def rename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_premium(uid) and get_credit(uid) <= 0:
        await update.message.reply_text("‼️ Akses Ditolak. Hubungi owner.")
        return
    context.user_data["waiting_zip"] = True
    await update.message.reply_text("Kirim file ZIP APK, lalu kirim:\n`domain_lama domain_baru port_lama port_baru`\nContoh: `example.com mydomain.com 8080 3000`", parse_mode="Markdown")

async def handle_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_zip"): return
    doc = update.message.document
    if doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("Maks 200MB")
        return
    await update.message.reply_text("Mengunduh...")
    f = await doc.get_file()
    zip_path = os.path.join(mkdtemp(), doc.file_name)
    await f.download_to_drive(zip_path)
    context.user_data["zip_path"] = zip_path
    context.user_data["waiting_params"] = True
    await update.message.reply_text("✅ ZIP siap. Kirim parameter sekarang.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_params"): return
    parts = update.message.text.strip().split()
    if len(parts) < 2:
        await update.message.reply_text("Format salah. Minimal: domainlama domainbaru")
        return
    old_domain, new_domain = parts[0], parts[1]
    old_port = int(parts[2]) if len(parts) >= 3 else None
    new_port = int(parts[3]) if len(parts) >= 4 else None
    uid = update.effective_user.id
    if not deduct_credit(uid):
        await update.message.reply_text("Credit habis.")
        return
    zip_path = context.user_data["zip_path"]
    await update.message.reply_text(f"Memproses {old_domain} → {new_domain}...")
    try:
        out_zip, cnt = process_zip(zip_path, old_domain, new_domain, old_port, new_port)
        await update.message.reply_document(open(out_zip, 'rb'), filename="modified.zip", caption=f"✅ {cnt} file .dart diubah")
        os.remove(zip_path); os.remove(out_zip)
        shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal: {e}")
    finally:
        context.user_data.clear()

async def add_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uid, amt = int(context.args[0]), int(context.args[1])
    users = load_users()
    uid_str = str(uid)
    users[uid_str] = users.get(uid_str, {"premium": False, "credit": 0})
    users[uid_str]["credit"] = users[uid_str].get("credit", 0) + amt
    save_users(users)
    await update.message.reply_text(f"+{amt} credit untuk {uid}")

async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uid, premium = int(context.args[0]), context.args[1].lower() == 'true'
    users = load_users()
    uid_str = str(uid)
    users[uid_str] = users.get(uid_str, {"premium": False, "credit": 0})
    users[uid_str]["premium"] = premium
    save_users(users)
    await update.message.reply_text(f"Premium {uid} = {premium}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rename", rename_cmd))
    app.add_handler(CommandHandler("addcredit", add_credit))
    app.add_handler(CommandHandler("setpremium", set_premium))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling()

if __name__ == "__main__":
    main()