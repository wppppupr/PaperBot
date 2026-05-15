import datetime
import arxiv
import argparse
import os
from habanero import Crossref
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

def fetch_papers(keywords, days):
    last_week = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    content = f"# Weekly Active Matter Papers ({last_week} to {datetime.datetime.now().strftime('%Y-%m-%d')})\n\n"

    print("Fetching from arXiv...")
    # 1. arXivから取得
    content += "## arXiv\n"
    client = arxiv.Client()
    search = arxiv.Search(query=f'all:"{keywords}"', max_results=100, sort_by=arxiv.SortCriterion.SubmittedDate)
    
    arxiv_count = 0
    for result in client.results(search):
        # 厳密なフレーズマッチングのフィルタリング
        if keywords.lower() not in result.title.lower() and keywords.lower() not in result.summary.lower():
            continue
            
        content += f"- **{result.title}**\n  - URL: {result.entry_id}\n  - Summary: {result.summary[:200].replace(chr(10), ' ')}...\n\n"
        arxiv_count += 1
        if arxiv_count >= 10:
            break

    print("Fetching from Crossref (Selected Journals)...")
    # 2. 指定したジャーナルからのみ取得
    content += "## Selected High-Impact Journals\n"
    
    # 指定されたジャーナルのISSNリスト
    target_issns = [
        '1745-2481', '2041-1723', '0027-8424', '2752-6542', 
        '2470-0045', '2160-3308', '0031-9007', '1744-683X', 
        '2375-2548', '1530-6984', '0743-7463', '1936-0851'
    ]

    cr = Crossref()
    
    # フィルタにissnを追加
    res = cr.works(
        query=f'"{keywords}"', 
        filter={
            'from-pub-date': last_week,
            'issn': target_issns
        }, 
        limit=500,
        sort='published', 
        order='desc'
    )
    
    for item in res['message']['items']:
        title = item.get('title', ['No Title'])[0]
        abstract = item.get('abstract', '')
        
        # 厳密なフレーズマッチングのフィルタリング
        if keywords.lower() not in title.lower() and keywords.lower() not in abstract.lower():
            continue
            
        doi = item.get('DOI', 'No DOI')
        url = item.get('URL', f"https://doi.org/{doi}")
        journal = item.get('container-title', ['Unknown'])[0]
        
        content += f"- **{title}** ({journal})\n  - DOI: {doi}\n  - URL: {url}\n\n"

    return content

def save_to_local(content, filename):
    # Ensure directory exists if there is a folder in filename
    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"File saved successfully as: {filename}")

def upload_to_gdrive(file_path):
    """Uploads a file to Google Drive."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials.json'):
                print("Error: 'credentials.json' not found.")
                print("Please download 'credentials.json' from Google Cloud Console and place it in the current directory.")
                return
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('drive', 'v3', credentials=creds)
        
        # フォルダ名の設定
        folder_name = 'Paper bot'
        
        # 既存のフォルダを検索
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        items = results.get('files', [])
        
        if not items:
            # フォルダが存在しない場合は作成
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(body=folder_metadata, fields='id').execute()
            folder_id = folder.get('id')
            print(f"Created new folder '{folder_name}' with ID: {folder_id}")
        else:
            # 存在する場合は最初のフォルダを使用
            folder_id = items[0].get('id')
            print(f"Found existing folder '{folder_name}' with ID: {folder_id}")
            
        file_metadata = {
            'name': os.path.basename(file_path),
            'parents': [folder_id]
        }
        media = MediaFileUpload(file_path, mimetype='text/markdown')
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        print(f"File uploaded successfully to Google Drive! File ID: {file.get('id')}")
    except Exception as error:
        print(f"An error occurred while uploading to Google Drive: {error}")

if __name__ == "__main__":
    # --- 設定 ---
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords', type=str, default="active matter")
    parser.add_argument('--days', type=int, default=1)
    parser.add_argument('--filename', type=str, default=None)
    parser.add_argument('--save_folder', type=str, default=None)
    parser.add_argument('--upload', action='store_true', help="Upload the generated file to Google Drive")
    
    args = parser.parse_args()
    keywords = args.keywords
    days = args.days
    filename = args.filename
    save_folder = args.save_folder
    upload = args.upload

    if filename is None:
        filename = f"Active_Matter_Review_{datetime.date.today()}.md"
    else:
        filename = f"{filename}.md"
    
    if save_folder is not None:
        filename = f"{save_folder}/{filename}"
    else:
        filename = f"papers/{filename}"

    print("Start fetching papers...")
    papers_content = fetch_papers(keywords, days)
    save_to_local(papers_content, filename)
    
    if upload:
        print("Uploading to Google Drive...")
        upload_to_gdrive(filename)
        
    print("Done!")
