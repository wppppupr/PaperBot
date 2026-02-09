import requests
import datetime
import google.generativeai as genai
import os

# ================= 設定エリア =================
API_KEY = "AIzaSyDqnPBa9SLpCj7ygH56PooWQLfGtJVf48o"
KEYWORDS = ["active matter", "self-propelled"]
SEARCH_DAYS = 7  # 過去7日分
MAX_RESULTS = 15 # 処理する論文の最大数
OUTPUT_FILE = "active_matter_report.md"
# =============================================

def fetch_crossref_papers(keywords, days):
    """Crossref APIから指定キーワードで最新論文を取得"""
    from_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    base_url = "https://api.crossref.org/works"
    
    # 複数キーワードを OR で検索
    query_str = " OR ".join([f'"{k}"' for k in keywords])
    params = {
        "query.bibliographic": query_str,
        "filter": f"from-pub-date:{from_date}",
        "sort": "published",
        "order": "desc",
        "rows": MAX_RESULTS
    }
    
    print(f"--- Crossrefから検索中: {query_str} (過去{days}日分) ---")
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        items = response.json().get('message', {}).get('items', [])
        return items
    except Exception as e:
        print(f"API取得エラー: {e}")
        return []

def summarize_with_gemini(papers):
    """Gemini APIを使用して、物理学者の視点で要約を生成"""
    if not papers:
        return "新しい論文は見つかりませんでした。"

    genai.configure(api_key=API_KEY)
    # 研究者向けのコンテキストを設定
    model = genai.GenerativeModel(
        model_name='gemini-1.5-flash',
        system_instruction="あなたはアクティブマターと統計物理学を専門とする物理学研究者です。提供された論文リストから学術的価値が高いものを厳選し、日本語で構造化されたレポートを作成してください。"
    )
    
    # 論文情報の整形
    paper_list_text = ""
    for i, p in enumerate(papers):
        title = p.get('title', ['No Title'])[0]
        journal = p.get('container-title', ['Unknown'])[0]
        doi = p.get('DOI', 'No DOI')
        # AbstractがCrossrefに含まれる場合はそれも送る（含まれない場合が多いのでタイトルと雑誌名が主）
        paper_list_text += f"[{i+1}] Title: {title}\nJournal: {journal}\nDOI: {doi}\n\n"

    prompt = f"""
    以下の論文リスト（直近公開分）を解析し、アクティブマターの最新動向をまとめてください。
    
    ### 依頼事項:
    1. 全体のトレンドを2〜3行で要約
    2. 特に注目すべき論文を3〜5件ピックアップし、以下の形式で解説：
       - **論文名（日本語訳）**
       - **概要**: 何を解決しようとしているか、どのような手法（実験・理論・数値計算）か
       - **物理的意義**: アクティブマターの文脈で何が新しいのか
       - [DOIリンク]
    
    論文リスト:
    {paper_list_text}
    """
    
    print("--- Geminiによる解析中 ---")
    response = model.generate_content(prompt)
    return response.text

def main():
    # 1. 取得
    papers = fetch_crossref_papers(KEYWORDS, SEARCH_DAYS)
    
    # 2. 要約
    report = summarize_with_gemini(papers)
    
    # 3. 保存
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n--- 完了！ ---")
    print(f"レポートを '{OUTPUT_FILE}' に保存しました。")
    print("\n【レポートプレビュー】\n")
    print(report[:500] + "...")

if __name__ == "__main__":
    main()