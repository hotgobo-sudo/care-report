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

# ドライブとスプレッドシート両方の権限
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

# --- フォント登録（修正：subfontIndexを追加） ---
if os.path.exists(FONT_PATH):
    try:
        # .ttcファイルの場合、subfontIndex=0 を指定することでエラーを回避します
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH, subfontIndex=0))
    except Exception as e:
        st.error(f"フォント読み込みエラー: {e}")
else:
    st.error(f"【重要】'{FONT_PATH}' が見見つかりません。")

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

# --- PDF作成ロジック ---
def create_styled_pdf_bytes(data):
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm)
        elements = []
        
        # スタイル設定
        normal_style = ParagraphStyle(name='L', fontName=FONT_NAME, fontSize=13, leading=22)
        title_style = ParagraphStyle(name='T', fontName=FONT_NAME, fontSize=24, alignment=1)
        table_cell_style = ParagraphStyle(name='Cell', fontName=FONT_NAME, fontSize=12, leading=16)

        elements.append(Paragraph("介護報告書", title_style))
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph(f"氏名： {data['name']} 様", normal_style))
        elements.append(Paragraph(f"報告日: {data['date']}", normal_style))
        elements.append(Spacer(1, 10*mm))

        # サービス項目
        t_data = [[Paragraph("サービス項目", table_cell_style), Paragraph("提供方法", table_cell_style), Paragraph("備考", table_cell_style)]]
        for item, info in data['items'].items():
            t_data.append([Paragraph(item, table_cell_style), Paragraph(info['method'], table_cell_style), Paragraph(info['note'], table_cell_style)])
        
        st_table = Table(t_data, colWidths=[40*mm, 40*mm, 90*mm])
        st_table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 0.5, colors.black), ('BACKGROUND', (0,0), (-1,0), colors.whitesmoke)]))
        elements.append(st_table)
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph("【支援経過】", normal_style))
        elements.append(Paragraph(data['progress'].replace('\n', '<br/>'), normal_style))

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
        pw = st.text_input("パスワードを入力してください", type="password")
        if st.button("ログイン"):
            if pw == PASSWORD:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("パスワードが違います")
        return False
    return True

# --- メイン UI ---
if check_password():
    ensure_sheet_header()

    with st.sidebar:
        st.header("操作メニュー")
        if st.button("🔄 入力内容をリセット"):
            for k in ["name_val", "prog_val", "author_val"]:
                if k in st.session_state: st.session_state[k] = ""
            st.rerun()

    st.title("📄 介護報告書 作成")
    
    # フォームの定義
    with st.form("main_form"):
        c1, c2 = st.columns(2)
        with c1: u_name = st.text_input("氏名（利用者様）", key="name_val")
        with c2: a_name = st.text_input("作成者", key="author_val")
        r_date = st.date_input("報告日", datetime.now())
        
        st.divider()
        items_list = ["健康管理", "入浴支援", "趣味活動推進", "口腔機能向上", "心身機能維持", "他者交流"]
        results = {}
        for item in items_list:
            col_sel, col_note = st.columns([1.5, 1])
            with col_sel: m = st.radio(item, ["通常提供", "積極提供", "本人に合わせる"], horizontal=True, key=f"r_{item}")
            with col_note: n = st.text_input("備考", key=f"n_{item}")
            results[item] = {"method": m, "note": n}

        p_text = st.text_area("支援経過", height=200, key="prog_val")
        submitted = st.form_submit_button("PDFを作成して保存", type="primary")

    # 【重要】ダウンロードボタンなどの処理はフォームの外（インデントを戻す）に書く
    if submitted:
        if not u_name or not a_name:
            st.error("氏名と作成者を入力してください。")
        else:
            report_data = {"name": u_name, "author": a_name, "date": r_date.strftime('%Y/%m/%d'), "items": results, "progress": p_text}
            f_name = f"{u_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

            with st.spinner("処理中..."):
                pdf_bytes, err = create_styled_pdf_bytes(report_data)
                if not err:
                    link, err2 = upload_pdf_to_drive(f_name, pdf_bytes)
                    save_history(u_name, report_data)
                    st.success("✅ 保存が完了しました！")
                    if link:
                        st.markdown(f"[📂 Google Driveで開く]({link})")
                    # フォームの外なので st.download_button が使えます
                    st.download_button(label="⬇️ PDFをダウンロード", data=pdf_bytes, file_name=f_name, mime="application/pdf")
                else:
                    st.error(f"作成エラー: {err}")