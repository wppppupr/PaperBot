import datetime
import arxiv
import argparse
import os
import requests
from habanero import Crossref
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Discord Webhook for error
DISCORD_ERROR = 'https://discord.com/api/webhooks/1505023099492372672/tcsWs9KogPc0J6tSleMws5OXvndX0CIOSibVkl8khUuNNSIl-pA8J3KP0BFNLvkmBTdF'
ARXIV_PAGE_SIZE = 30


def fetch_papers(keywords_list, days):
    last_day = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    keywords_str = ", ".join(keywords_list)
    content = f"# Daily Papers for {keywords_str} ({last_day} to {datetime.datetime.now().strftime('%Y-%m-%d')})\n\n"

    print("Fetching from arXiv...")
    # 1. arXivから取得
    content += "## arXiv\n"
    client = arxiv.Client(
        page_size=ARXIV_PAGE_SIZE,
        delay_seconds=3.0,
        num_retries=5
        )
    
    arxiv_query = " OR ".join([f'all:"{k}"' for k in keywords_list])
    search = arxiv.Search(query=arxiv_query, max_results=ARXIV_PAGE_SIZE, sort_by=arxiv.SortCriterion.SubmittedDate)
    
    arxiv_count = 0
    for result in client.results(search):
        # 厳密なフレーズマッチングのフィルタリング
        if not any(k.lower() in result.title.lower() or k.lower() in result.summary.lower() for k in keywords_list):
            continue
            
        content += f"- **{result.title}**\n -Authors: {', '.join(author.name for author in result.authors)} \n -Date: {result.updated.strftime('%Y-%m-%d')} \n - URL: {result.entry_id}\n  - Summary: {result.summary[:200].replace(chr(10), ' ')}...\n\n"
        
        """arxiv_count += 1
        if arxiv_count >= 10:
            break"""

    print("Fetching from Crossref (Selected Journals)...")
    # 2. 指定したジャーナルからのみ取得
    content += "## Selected High-Impact Journals\n"
    
    # 指定されたジャーナルのISSNリスト
    target_issns = [
        '1476-4687', '1755-4349', '1745-2481', '2041-1723', '1476-4660', '0027-8424', 
        '2752-6542', '2470-0045', '2160-3308', '0031-9007', '1744-683X', '2375-2548', 
        '1530-6984', '0743-7463', '1936-0851', '2835-8279', '1095-9203', '1549-9626'
    ]

    """
    Nature, Nature Chemistry, Nature Physics, Nature Communications, Nature materials, PNAS, 
    PNAS-Nexus, Physical Review E, Physical Review X, Physical Review Letters, Soft Matter, Science Advances, 
    Nano Letters, Langmuir, ACS nano, PRX Life, Science, JCTC, 
    """

    cr = Crossref()
    
    seen_dois = set()
    
    for keyword in keywords_list:
        # フィルタにissnを追加
        res = cr.works(
            query=f'"{keyword}"', 
            filter={
                'from-pub-date': last_day,
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
            if keyword.lower() not in title.lower() and keyword.lower() not in abstract.lower():
                continue
                
            doi = item.get('DOI', 'No DOI')
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
            
            url = item.get('URL', f"https://doi.org/{doi}")
            journal = item.get('container-title', ['Unknown'])[0]
            
            # Crossref用の著者と日付の抽出
            authors_list = item.get('author', [])
            author_names = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in authors_list]
            authors_str = ', '.join(author_names) if author_names else 'Unknown'
            
            published = item.get('published-print', item.get('published-online', item.get('created', {})))
            date_parts = published.get('date-parts', [[None]])[0]
            if date_parts and date_parts[0]:
                date_str = '-'.join(f"{p:02d}" for p in date_parts if p)
            else:
                date_str = "Unknown"
            
            content += f"- **{title}** ({journal})\n -Authors: {authors_str}\n -Date: {date_str}\n - DOI: {doi}\n  - URL: {url}\n\n"

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

def send_to_discord(file_path, webhook_url):
    """Sends the generated file content as messages to a Discord webhook."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 論文単位で分割する
        chunks = []
        current_chunk = ""
        
        for line in content.split('\n'):
            if line.startswith('- **') or line.startswith('## ') or line.startswith('# '):
                # 新しい論文や見出しの始まりなので、これまでのまとまりを分割
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = line + '\n'
            else:
                current_chunk += line + '\n'
                
                # 万が一1つのエントリが1900文字を超える場合のフェイルセーフ
                if len(current_chunk) > 1900:
                    chunks.append(current_chunk[:1900])
                    current_chunk = current_chunk[1900:]
                    
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
            
        for i, chunk in enumerate(chunks):
            response = requests.post(
                webhook_url,
                json={'content': chunk}
            )
            if response.status_code not in [200, 204]:
                print(f"Failed to send chunk {i+1} to Discord. Status code: {response.status_code}")
                return
                
        print("Successfully sent to Discord as messages!")
    except Exception as e:
        print(f"An error occurred while sending to Discord: {e}")

if __name__ == "__main__":
    # --- 設定 ---
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords', type=str, nargs='+', default=["active matter", "microtubules", "actin", "motor proteins", "kinesin", "myosin", "dynein", "Living matter & active matter", "Colloids", "Nonlinear"], help="One or more keywords for OR search (e.g., --keywords 'active matter' 'liquid crystal')")
    parser.add_argument('--days', type=int, default=1)
    parser.add_argument('--filename', type=str, default=None)
    parser.add_argument('--save_folder', type=str, default=None)
    parser.add_argument('--upload', action='store_true', help="Upload the generated file to Google Drive")
    parser.add_argument('--discord_webhook', type=str, default="https://discord.com/api/webhooks/1504761505151844433/C9Ns2fw9IAjhBcUOnP4TqQ4bwOqnYUUd8WxlDVN1MZ9_R1nd3_3Y7H7HFwEJtCS2voxJ", help="Discord Webhook URL to send the report")
    
    args = parser.parse_args()
    keywords_list = args.keywords
    days = args.days
    filename = args.filename
    save_folder = args.save_folder
    upload = args.upload
    discord_webhook = args.discord_webhook

    print("Start paper bot at", datetime.datetime.now())

    if filename is None:
        safe_keyword = keywords_list[0].replace(' ', '_')
        filename = f"{safe_keyword}_Review_{datetime.date.today()}.md"
    else:
        filename = f"{filename}.md"
    
    if save_folder is not None:
        filename = f"{save_folder}/{filename}"
    else:
        filename = f"papers/{filename}"

    try:    
        print("Start fetching papers...")
        papers_content = fetch_papers(keywords_list, days)
        save_to_local(papers_content, filename)
        
        if upload:
            print("Uploading to Google Drive...")
            upload_to_gdrive(filename)
            
        if discord_webhook:
            print("Sending to Discord...")
            send_to_discord(filename, discord_webhook)

        if upload or discord_webhook:
            if os.path.exists(filename):
                os.remove(filename)
            
        print("Done!")

    except Exception as e:
        import traceback
        
        # エラーのスタックトレース（詳細）を取得
        error_msg = traceback.format_exc()
        print("An error occurred during execution:")
        print(error_msg)
        
        # Discordの通知用テキスト（2000文字制限を考慮してスライス）
        discord_error_text = (
            "<@520785852423733248> \n"
            f"❌ **【Paper Bot エラー通知】**\n"
            f"プログラムの実行中にエラーが発生しました。\n"
            f"```python\n{error_msg}```"
        )[:1950]
        
        # Webhookを使ってエラーをDiscordに送信
        try:
            requests.post(DISCORD_ERROR, json={'content': discord_error_text})
            print("Error notification sent to Discord.")
        except Exception as send_err:
            print(f"Failed to send error notification to Discord: {send_err}")