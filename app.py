import streamlit as st
import json
import os
import io
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- 設定項目 ---
PASSWORD = "care1234"
FONT_NAME = 'JP-Font'
FONT_PATH = 'msmincho.ttc'

# Streamlit Secrets から取得
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"] 

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file"
]

# --- Google認証 ---
@st.cache_resource
def get_google_clients():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return gc, drive_service

# --- フォント登録 ---
if os.path.exists(FONT_PATH):
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
else:
    st.error(f"【重要】'{FONT_PATH}' が見つかりません。")

# --- 履歴管理（Google Sheets） ---
def save_history(name, data):
    try:
        gc, _ = get_google_clients()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet("care_history")
        row = [
            name, data["date"], data["author"],
            json.dumps(data["items"], ensure_ascii=False),
            data["progress"], datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.warning(f"履歴の保存に失敗しました: {e}")

def get_all_history(name):
    try:
        gc, _ = get_google_clients()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet("care_history")
        all_rows = ws.get_all_values()
        matched = [r for r in reversed(all_rows[1:]) if len(r) >= 5 and r[0] == name]
        result = []
        for r in matched[:10]:
            try: items = json.loads(r[3])
            except: items = {}
            result.append({"name": r[0], "date": r[1], "author": r[2], "items": items, "progress": r[4]})
        return result
    except: return []

def ensure_sheet_header():
    try:
        gc, _ = get_google_clients()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet("care_history")
        if not ws.row_values(1):
            ws.append_row(["氏名", "報告日", "作成者", "サービス項目(JSON)", "支援経過", "登録日時"])
    except: pass

# --- PDF作成 ---
def create_styled_pdf_bytes(data):
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)
        elements = []
        normal_style = ParagraphStyle(name='L', fontName=FONT_NAME, fontSize=13, leading=22)
        elements.append(Paragraph(f"介護報告書 - {data['name']} 様", normal_style))
        # （中略：本来は詳細なテーブル作成が入りますが動作確認用に簡略化。必要なら元のPDFロジックをここへ）
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph(f"支援経過: {data['progress']}", normal_style))
        doc.build(elements)
        buffer.seek(0)
        return buffer.read(), None
    except Exception as e: return None, str(e)

# --- Drive保存 ---
def upload_pdf_to_drive(filename, pdf_bytes):
    try:
        _, drive_service = get_google_clients()
        file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
        uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute()
        return uploaded.get("webViewLink"), None
    except Exception as e: return None, str(e)

# --- 認証機能 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.title("ログイン")
        st.text_input("パスワードを入力", type="password", key="pw_input")
        if st.button("ログイン"):
            if st.session_state["pw_input"] == PASSWORD:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("パスワードが違います")
        return False
    return True

# --- メイン UI ---
if check_password():
    ensure_sheet_header()
    st.title("📄 介護報告書 作成")
    
    with st.form("main_form"):
        u_name = st.text_input("氏名", key="name_val")
        a_name = st.text_input("作成者", key="author_val")
        p_text = st.text_area("支援経過", key="prog_val")
        submitted = st.form_submit_button("保存")

        if submitted:
            report_data = {"name": u_name, "author": a_name, "date": datetime.now().strftime('%Y/%m/%d'), "items": {}, "progress": p_text}
            pdf_bytes, err = create_styled_pdf_bytes(report_data)
            if not err:
                link, err2 = upload_pdf_to_drive(f"{u_name}.pdf", pdf_bytes)
                if not err2:
                    save_history(u_name, report_data)
                    st.success("保存完了！")
                    st.markdown(f"[Driveで見る]({link})")
                else: st.error(err2)