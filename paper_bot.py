import os
import datetime
from arxiv import Search, SortCriterion
from habanero import Crossref
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# --- 設定 ---
KEYWORDS = '"active matter"'
DRIVE_FOLDER_ID = '1lEScToNI9VgEw8EnO_z5P3JBSeYIu6NC' # フォルダURLの末尾の英数字
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def get_drive_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

def fetch_papers():
    last_week = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
    content = f"# Weekly Active Matter Papers ({last_week} to {datetime.datetime.now().strftime('%Y-%m-%d')})\n\n"

    # 1. arXivから取得 (ここは広めに拾うため変更なし)
    content += "## arXiv\n"
    search = Search(query=f'all:{KEYWORDS}', max_results=10, sort_by=SortCriterion.SubmittedDate)
    for result in search.results():
        content += f"- **{result.title}**\n  - URL: {result.entry_id}\n  - Summary: {result.summary[:200]}...\n\n"

    # 2. 指定したジャーナルからのみ取得
    content += "## Selected High-Impact Journals\n"
    
    # 指定されたジャーナルのISSNリスト
    target_issns = [
        '1745-2481', '2041-1723', '0027-8424', '2752-6542', 
        '2470-0045', '2160-3308', '0031-9007', '1744-683X', 
        '2375-2548', '1530-6984', '0743-7463', '1936-0851'
    ]

    cr = Crossref()
    
    # フィルタにissnを追加。Crossrefは複数のISSNをカンマ区切りで受け付けます。
    res = cr.works(
        query=KEYWORDS, 
        filter={
            'from-pub-date': last_week,
            'issn': target_issns
        }, 
        limit=200, # ジャーナルを絞った分、取得件数を少し増やしても良いかもしれません
        sort='published', 
        order='desc'
    )
    
    for item in res['message']['items']:
        # 稀にタイトルがリスト形式で返ることがあるため処理
        title = item.get('title', ['No Title'])[0]
        doi = item.get('DOI', 'No DOI')
        url = item.get('URL', f"https://doi.org/{doi}")
        journal = item.get('container-title', ['Unknown'])[0]
        
        content += f"- **{title}** ({journal})\n  - DOI: {doi}\n  - URL: {url}\n\n"
        

    return content

def upload_to_drive(service, content):
    filename = f"Active_Matter_Review_{datetime.date.today()}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    file_metadata = {
        'name': filename,
        'parents': [DRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(filename, mimetype='text/markdown')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"Uploaded File ID: {file.get('id')}")

if __name__ == "__main__":
    service = get_drive_service()
    papers_content = fetch_papers()
    upload_to_drive(service, papers_content)