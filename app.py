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
DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]  # ここが抜けていると保存できません

# 【修正ポイント2】スコープに Drive API を追加
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file"
]

# --- Google認証 ---
# 【修正ポイント3】Google Sheets と Drive 両方のクライアントを初期化
@st.cache_resource
def get_google_clients():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=SCOPES
        )
        # Sheets API用
        gc = gspread.authorize(creds)
        # Drive API用
        drive_service = build('drive', 'v3', credentials=creds)
        
        return gc, drive_service
    except Exception as e:
        st.error(f"Google認証に失敗しました: {e}")
        return None, None

# --- フォント登録 ---
if os.path.exists(FONT_PATH):
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
else:
    st.error(f"【重要】'{FONT_PATH}' が見つかりません。")

# --- 履歴管理（Google Sheets） ---
def save_history(name, data):
    try:
        # 戻り値がタプルになったので gc のみ受け取る
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
# 【修正ポイント4】引数を受け取り、適切にアップロードを実行
def upload_pdf_to_drive(filename, pdf_bytes):
    try:
        # 修正された認証関数から Drive サービスを取得
        _, drive_service = get_google_clients()
        if not drive_service:
            return None, "Drive API クライアントの初期化に失敗しました。"
        
        file_metadata = {
            "name": filename,
            "parents": [DRIVE_FOLDER_ID]
        }
        media = MediaIoBaseUpload(io.BytesIO(pdf_bytes), mimetype="application/pdf")
        
        uploaded = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True  # 共有ドライブ対応
        ).execute()
        
        return uploaded.get("webViewLink"), None
    except Exception as e:
        error_msg = str(e)
        # エラーハンドリング：権限や容量不足の場合
        if "403" in error_msg or "quota" in error_msg.lower():
            return None, f"Drive保存不可（権限/容量）。手動保存してください。"
        return None, f"Drive保存エラー: {error_msg}"

# --- 認証機能 (check_password以降は既存と同じため省略可、必要なら統合) ---
# ... (以下、streamlitのメインロジック)