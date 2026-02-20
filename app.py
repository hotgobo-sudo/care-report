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
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"] # ドライブ保存に必須

# 【修正1】スコープに Drive API を追加
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
    # Sheets API
    gc = gspread.authorize(creds)
    # 【修正2】Drive API サービスを初期化
    drive_service = build('drive', 'v3', credentials=creds)
    return gc, drive_service

# --- フォント登録 ---
if os.path.exists(FONT_PATH):
    try:
        # 【修正3】.ttc 形式特有の読み込みエラーを回避
        pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH, subfontIndex=0))
    except Exception as e:
        st.error(f"フォント登録エラー: {e}")
else:
    st.error(f"【重要】'{FONT_PATH}' が見つかりません。")

# --- 履歴管理（Google Sheets） ---
def save_history(name, data):
    try:
        gc, _ = get_google_clients()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet("care_history")
        row = [
            name,
            data["date"],
            data["author"],
            json.dumps(data["items"], ensure_ascii=False),
            data["progress"],
            datetime.now().strftime("%Y/%m/%d %H:%M:%S")
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
            try:
                items = json.loads(r[3])
            except:
                items = {}
            result.append({
                "name": r[0],
                "date": r[1],
                "author": r[2],
                "items": items,
                "progress": r[4]
            })
        return result
    except Exception as e:
        st.warning(f"履歴の取得に失敗しました: {e}")
        return []

def ensure_sheet_header():
    try:
        gc, _ = get_google_clients()
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet("care_history")
        first_row = ws.row_values(1)
        if not first_row:
            ws.append_row(["氏名", "報告日", "作成者", "サービス項目(JSON)", "支援経過", "登録日時"])
    except Exception as e:
        pass

# --- PDF作成ロジック ---
def create_styled_pdf_bytes(data):
    try:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                rightMargin=20*mm, leftMargin=20*mm,
                                topMargin=15*mm, bottomMargin=15*mm)
        elements = []

        title_size, header_size, name_size, normal_size, table_font_size = 24, 14, 18, 13, 12
        title_style  = ParagraphStyle(name='T',    fontName=FONT_NAME, fontSize=title_size)
        header_style = ParagraphStyle(name='H',    fontName=FONT_NAME, fontSize=header_size)
        name_style   = ParagraphStyle(name='N',    fontName=FONT_NAME, fontSize=name_size, leading=26)
        normal_style = ParagraphStyle(name='L',    fontName=FONT_NAME, fontSize=normal_size, leading=22)
        center_style = ParagraphStyle(name='C',    fontName=FONT_NAME, fontSize=14, alignment=1)
        right_style  = ParagraphStyle(name='R',    fontName=FONT_NAME, fontSize=normal_size, alignment=2)
        table_cell_style = ParagraphStyle(name='Cell', fontName=FONT_NAME, fontSize=table_font_size, leading=16)

        h_data = [[Paragraph("介護報告書", title_style), Paragraph(f"報告日: {data['date']}", header_style)]]
        h_table = Table(h_data, colWidths=[110*mm, 60*mm])
        h_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'BOTTOM')]))
        elements.append(h_table)
        elements.append(Table([[""]], colWidths=[170*mm],
                               style=[('LINEBELOW', (0,0), (-1,-1), 1, colors.black)]))
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph(f"氏名： {data['name']} 様", name_style))
        elements.append(Spacer(1, 10*mm))

        t_data = [[Paragraph("サービス項目", table_cell_style),
                   Paragraph("提供方法", table_cell_style),
                   Paragraph("備考・詳細", table_cell_style)]]
        for item, info in data['items'].items():
            t_data.append([
                Paragraph(item, table_cell_style),
                Paragraph(info['method'], table_cell_style),
                Paragraph(info['note'] if info['note'] else "-", table_cell_style)
            ])

        service_table = Table(t_data, colWidths=[40*mm, 40*mm, 90*mm])
        service_table.setStyle(TableStyle([
            ('GRID',       (0,0), (-1,-1), 0.5, colors.black),
            ('BACKGROUND', (0,0), (-1,0),  colors.whitesmoke),
            ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3*mm),
            ('TOPPADDING',    (0,0), (-1,-1), 3*mm)
        ]))
        elements.append(service_table)
        elements.append(Spacer(1, 15*mm))
        elements.append(Paragraph("【支援経過】", normal_style))
        p_table = Table(
            [[Paragraph(data['progress'].replace('\n', '<br/>'), normal_style)]],
            colWidths=[170*mm]
        )
        p_table.setStyle(TableStyle([
            ('GRID',           (0,0), (-1,-1), 0.5, colors.black),
            ('LEFTPADDING',    (0,0), (-1,-1), 5*mm),
            ('TOPPADDING',     (0,0), (-1,-1), 5*mm),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 5*mm),
            ('MINSIZE',        (0,0), (-1,-1), 60*mm)
        ]))
        elements.append(p_table)
        elements.append(Spacer(1, 20*mm))
        elements.append(Paragraph("石狩ふれあい・ほっと館介護センター", center_style))
        elements.append(Spacer(1, 10*mm))
        elements.append(Paragraph(f"作成者： {data['author']}", right_style))

        doc.build(elements)
        buffer.seek(0)
        return buffer.read(), None
    except Exception as e:
        return None, str(e)

# --- Google DriveへPDFアップロード ---
def upload_pdf_to_drive(filename, pdf_bytes):
    try:
        # get_google_clients から 2つ目の戻り値を取得
        _, drive_service = get_google_clients()
        
        file_metadata = {
            "name": filename,
            "parents": [DRIVE_FOLDER_ID]
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
        
        uploaded = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True
        ).execute()
        return uploaded.get("webViewLink"), None
    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "quota" in error_msg.lower() or "storage" in error_msg.lower():
            return None, f"Drive保存をスキップ。ダウンロードボタンを使用してください。"
        return None, f"Drive保存エラー: {error_msg}"

# --- 認証機能 ---
def check_password():
    if "password_correct" not in st.session_state:
        st.title("ログイン")
        st.text_input("パスワードを入力してください", type="password",
                      on_change=lambda: st.session_state.update(
                          {"password_correct": st.session_state["pw"] == PASSWORD}),
                      key="pw")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("パスワードを入力してください", type="password",
                      on_change=lambda: st.session_state.update(
                          {"password_correct": st.session_state["pw"] == PASSWORD}),
                      key="pw")
        st.error("😕 パスワードが違います")
        return False
    return True

# --- メイン UI ---
if check_password():
    ensure_sheet_header()

    with st.sidebar:
        st.header("操作メニュー")

        if st.button("🔄 入力内容をリセット"):
            keys_to_reset = ["name_val", "prog_val", "author_val"]
            items_list = ["健康管理", "入浴支援", "趣味活動推進", "口腔機能向上", "心身機能維持", "他者交流"]
            for k in keys_to_reset:
                if k in st.session_state:
                    st.session_state[k] = ""
            for item in items_list:
                st.session_state[f"r_{item}"] = "通常提供"
                st.session_state[f"n_{item}"] = ""
            st.rerun()

        st.divider()
        st.subheader("履歴の検索・復元")
        s_name = st.text_input("氏名を入力")
        if s_name:
            hist_list = get_all_history(s_name)
            if hist_list:
                selected_index = st.selectbox(
                    "復元するデータを選択",
                    range(len(hist_list)),
                    format_func=lambda i: f"{hist_list[i].get('date', '不明')} の報告"
                )
                if st.button("このデータを復元"):
                    h = hist_list[selected_index]
                    st.session_state.update({
                        "name_val": h['name'],
                        "author_val": h['author'],
                        "prog_val": h['progress']
                    })
                    for item, info in h['items'].items():
                        st.session_state[f"r_{item}"] = info['method']
                        st.session_state[f"n_{item}"] = info['note']
                    st.rerun()
            else:
                st.info("履歴が見つかりません")

    st.title("📄 介護報告書 作成")
    with st.form("main_form"):
        c1, c2 = st.columns(2)
        with c1: u_name = st.text_input("氏名（利用者様）", key="name_val")
        with c2: a_name = st.text_input("作成者", key="author_val")
        r_date = st.date_input("報告日", datetime.now())
        st.divider()

        items_list = ["健康管理", "入浴支援", "趣味活動推進", "口腔機能向上", "心身機能維持", "他者交流"]
        options = ["通常提供", "積極提供", "本人に合わせる"]
        results = {}

        for item in items_list:
            col_sel, col_note = st.columns([1.5, 1])
            with col_sel:
                m = st.radio(item, options, horizontal=True, key=f"r_{item}")
            with col_note:
                n = st.text_input("備考（詳細）", key=f"n_{item}")
            results[item] = {"method": m, "note": n}

        st.divider()
        p_text = st.text_area("支援経過", height=200, key="prog_val")
        submitted = st.form_submit_button("PDFを作成して保存", type="primary")

        if submitted:
            if not u_name or not a_name:
                st.error("氏名と作成者を入力してください。")
            else:
                report_data = {
                    "name":     u_name,
                    "author":   a_name,
                    "date":     r_date.strftime('%Y/%m/%d'),
                    "items":    results,
                    "progress": p_text
                }
                f_name = f"{u_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

                with st.spinner("PDFを作成・保存中..."):
                    pdf_bytes, err = create_styled_pdf_bytes(report_data)
                    if err:
                        st.error(f"PDF作成エラー: {err}")
                    else:
                        link, err2 = upload_pdf_to_drive(f_name, pdf_bytes)
                        if err2:
                            st.error(f"Driveへの保存エラー: {err2}")
                        else:
                            save_history(u_name, report_data)
                            st.balloons()
                            st.success(f"✅ 保存完了！")
                            if link:
                                st.markdown(f"[📂 Google DriveでPDFを開く]({link})")
                            
                            st.download_button(
                                label="⬇️ PDFをダウンロード",
                                data=pdf_bytes,
                                file_name=f_name,
                                mime="application/pdf"
                            )