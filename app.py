import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

st.title("🔍 Google Drive 権限チェック")

try:
    DRIVE_FOLDER_ID = st.secrets["DRIVE_FOLDER_ID"]
    
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    
    st.write("### サービスアカウント情報")
    st.code(st.secrets["gcp_service_account"]["client_email"])
    st.info("👆 このメールアドレスを Google Drive で共有してください")
    
    st.write("### フォルダ情報取得")
    drive_service = build("drive", "v3", credentials=creds)
    
    # フォルダ情報を取得
    folder = drive_service.files().get(
        fileId=DRIVE_FOLDER_ID,
        fields="id, name, permissions, capabilities"
    ).execute()
    
    st.success(f"✅ フォルダ名: {folder['name']}")
    
    # 権限の詳細
    st.write("### 現在の権限")
    if "permissions" in folder:
        for perm in folder["permissions"]:
            st.write(f"- **{perm.get('emailAddress', perm.get('id'))}**: {perm['role']}")
    else:
        st.warning("権限情報を取得できませんでした（フィールド指定が必要）")
    
    # 実行可能な操作
    st.write("### 実行可能な操作")
    caps = folder.get("capabilities", {})
    st.write(f"- ファイルを追加できる: {'✅' if caps.get('canAddChildren') else '❌'}")
    st.write(f"- 編集できる: {'✅' if caps.get('canEdit') else '❌'}")
    
    if not caps.get('canAddChildren'):
        st.error("""
        ❌ ファイルを追加する権限がありません
        
        対処法:
        1. Google Driveでこのフォルダを開く
        2. 右クリック → 「共有」
        3. 上記のメールアドレスを「編集者」として追加
        """)
    else:
        st.success("✅ すべての権限が正常です！")
        st.balloons()
        
except Exception as e:
    st.error(f"エラー: {e}")
    
    if "404" in str(e):
        st.warning("DRIVE_FOLDER_ID が間違っている可能性があります")
    elif "403" in str(e):
        st.warning("""
        フォルダにアクセスできません。
        
        確認事項:
        1. DRIVE_FOLDER_ID が正しいか
        2. サービスアカウントのメールが「編集者」として共有されているか
        """)