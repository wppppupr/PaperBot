import datetime
import arxiv
import requests
import time
import argparse
import os
import re
import google.generativeai as genai

# -----------------------------
# 設定
# -----------------------------
ARXIV_PAGE_SIZE = 50
OPENALEX_MAILER = os.getenv("OPENALEX_MAILER", "your-email@example.com")  # Polite pool用

gemini_API_key = os.getenv('GEMINI_API_KEY', '')
genai.configure(api_key=gemini_API_key)

import json
import time

def translate_abstracts_batch(abstracts):
    if not abstracts:
        return []
    
    translated = []
    chunk_size = 10
    model = genai.GenerativeModel("gemini-3.1-flash-lite")
    
    for i in range(0, len(abstracts), chunk_size):
        chunk = abstracts[i:i+chunk_size]
        prompt = "以下のJSON配列（英語の論文要約のリスト）を、同じ要素数のJSON配列として日本語に翻訳して出力してください。出力はJSON配列のみにしてください。\n\n"
        prompt += json.dumps(chunk, ensure_ascii=False)
        
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```json"): text = text[7:]
            elif text.startswith("```"): text = text[3:]
            if text.endswith("```"): text = text[:-3]
            text = text.strip()
            
            chunk_translated = json.loads(text)
            if isinstance(chunk_translated, list) and len(chunk_translated) == len(chunk):
                translated.extend([t.replace('\n', ' ') for t in chunk_translated])
            else:
                print(f"Warning: Batch size mismatch. Expected {len(chunk)}, got {len(chunk_translated) if isinstance(chunk_translated, list) else type(chunk_translated)}")
                translated.extend(["翻訳に失敗しました。"] * len(chunk))
        except Exception as e:
            print(f"Batch translation error: {e}")
            translated.extend(["翻訳に失敗しました。"] * len(chunk))
            
        if i + chunk_size < len(abstracts):
            time.sleep(10)  # RPM対策のウェイト
            
    return translated

# -----------------------------
# arXiv取得
# -----------------------------
def fetch_arxiv(keywords, days):
    print("Fetching from arXiv...")
    
    # タイムゾーンに依存しないようUTCで計算（arXivの基準に合わせる）
    target_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    
    # 検索クエリの構築
    keywords_query = " OR ".join([f'all:"{k}"' for k in keywords])

    # ターゲットとするカテゴリを定義
    cond_mat_categories = [
        "cond-mat.soft",       # ソフトマター
        "cond-mat.stat-mech",  # 統計力学
        "physics.bio-ph",      # 生物物理
        "physics.flu-dyn",     # 流体力学
        "nlin.PS",             # 非線形科学 - パターン形成
        "q-bio.CB"             # 分子生物学 - 生物学的計算
    ]
    cat_query = " OR ".join([f"cat:{c}" for c in cond_mat_categories])
    arxiv_query = f"({cat_query}) AND ({keywords_query})"

    client = arxiv.Client(page_size=ARXIV_PAGE_SIZE, delay_seconds=2)
    # 過去数日分の論文を網羅するため、max_resultsは少し多めに設定
    search = arxiv.Search(query=arxiv_query, max_results=200, sort_by=arxiv.SortCriterion.SubmittedDate)

    papers = []
    try:
        for r in client.results(search):
            # ⚠️ データ取りこぼし（バグ）を防ぐため、breakではなくcontinueを使用
            if r.updated < target_date:
                continue
                
            papers.append({
                "title": r.title,
                "authors": [a.name for a in r.authors],
                "date": r.updated.strftime('%Y-%m-%d'),
                "url": r.entry_id,
                "source": "arXiv",
                "abstract": r.summary
            })
    except Exception as e:
        print(f"arXiv error: {e}")

    # 重複除去の前に日付順でソート（最新順を担保）
    papers.sort(key=lambda x: x['date'] or "", reverse=True)

    print(f"arXiv: {len(papers)} papers")
    return papers

# -----------------------------
# OpenAlex取得
# -----------------------------
def reconstruct_abstract(inv_idx):
    if not inv_idx:
        return ""

    words = []
    for word, positions in inv_idx.items():
        for pos in positions:
            words.append((pos, word))

    words.sort()
    return " ".join(word for _, word in words)


def fetch_openalex(keywords, days, journal_issns=None):
    print("Fetching from OpenAlex...")

    last_day = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    query = " OR ".join([f'"{k}"' for k in keywords])

    url = "https://api.openalex.org/works"
    headers = {"User-Agent": f"PaperNotifier/1.0 (mailto:{OPENALEX_MAILER})"}
    papers = []

    filter_str = f"from_publication_date:{last_day}"
    if journal_issns:
        journals_filter = "|".join(journal_issns)
        filter_str += f",primary_location.source.issn:{journals_filter}"

    for page in range(1, 3):
        params = {
            "search": query,
            "filter": filter_str,
            "sort": "publication_date:desc",
            "per-page": 50,
            "page": page
        }

        try:
            res = requests.get(url, params=params, headers=headers, timeout=30)
            if res.status_code != 200:
                print(f"OpenAlex API returned status code {res.status_code}")
                continue

            data = res.json()

            for w in data.get("results", []):
                if not w.get("title"):
                    continue

                abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
                journal_name = w.get("primary_location", {}).get("source", {}).get("display_name", "Unknown Journal")
                
                papers.append({
                    "title": w.get("title"),
                    "authors": [a["author"]["display_name"] for a in w.get("authorships", []) if "author" in a],
                    "abstract": abstract,
                    "date": w.get("publication_date"),
                    "url": w.get("doi") or w.get("id"),
                    "source": f"OpenAlex ({journal_name})"
                })

        except Exception as e:
            print(f"OpenAlex error: {e}")

    #papers.sort(key=lambda x: x['date'] or "", reverse=True)
    print(f"OpenAlex: {len(papers)} papers")
    return papers

# -----------------------------
# 重複除去（正規化の強化）
# -----------------------------
def clean_title(title):
    if not title:
        return ""
    # 空白の正規化（改行や連続する半角スペースを1つに）
    title = re.sub(r'\s+', ' ', title.lower()).strip()
    # 末尾のピリオド等を除去
    title = title.rstrip('.')
    return title

def deduplicate(papers):
    seen = set()
    unique = []

    for p in papers:
        key = clean_title(p.get("title"))
        if not key or key in seen:
            continue

        seen.add(key)
        unique.append(p)

    print(f"After deduplication: {len(unique)} papers")
    return unique


# -----------------------------
# Markdown生成
# -----------------------------
def format_markdown(papers, keywords):
    today = datetime.date.today()

    content = f"# Daily Papers ({today})\n"
    content += f"Keywords: {', '.join(keywords)}\n\n"
    
    # --- 分類 ---
    arxiv = [p for p in papers if p["source"] == "arXiv"]
    openalex = [p for p in papers if p["source"].startswith("OpenAlex")]

    print(f"Translating abstracts...")
    ordered_papers_with_abstracts = [p for p in arxiv + openalex if p.get("abstract")]
    abstracts_to_translate = [p['abstract'].replace("\n", " ").strip() for p in ordered_papers_with_abstracts]
    translated_abstracts = translate_abstracts_batch(abstracts_to_translate)
    
    for i, p in enumerate(ordered_papers_with_abstracts):
        p['translated_abstract'] = translated_abstracts[i] if i < len(translated_abstracts) else "翻訳に失敗しました。"

    # --- arXiv ---
    content += "## 🧪 arXiv (Preprints)\n\n"

    if not arxiv:
        content += "_No papers found._\n\n"

    for p in arxiv:
        authors_str = ', '.join(p['authors'][:5])
        if len(p['authors']) > 5:
            authors_str += " et al."

        content += f"- **{p['title']}**\n"
        content += f"  - {authors_str}\n"
        content += f"  - {p['date']}\n"
        content += f"  - {p['url']}\n\n"

        if p.get("abstract"):
            abstract = p['abstract'].replace("\n", " ").strip()
            translated_abstract = p.get('translated_abstract', "翻訳に失敗しました。")
            content += f"  - **Abstract:**\n    > {abstract}\n  - **和訳:**\n    > {translated_abstract}\n\n"



    # --- OpenAlex（ジャーナル） ---
    content += "## 🧠 Journal Papers\n\n"

    if not openalex:
        content += "_No papers found._\n\n"

    for p in openalex:
        authors_str = ', '.join(p['authors'][:5])
        if len(p['authors']) > 5:
            authors_str += " et al."

        content += f"- **{p['title']}**\n"
        content += f"  - {authors_str}\n"
        content += f"  - {p['date']} | {p['source']}\n"
        content += f"  - {p['url']}\n\n"

        if p.get("abstract"):
            abstract = p['abstract'].replace("\n", " ").strip()
            translated_abstract = p.get('translated_abstract', "翻訳に失敗しました。")
            content += f"  - **Abstract:**\n    > {abstract}\n  - **和訳:**\n    > {translated_abstract}\n\n"


    return content

# -----------------------------
# 保存
# -----------------------------
def save_file(content, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved: {path}")


# -----------------------------
# Discord送信（チャンク処理の安全化）
# -----------------------------
def send_discord(file_path, webhook):
    print("Sending to Discord...")

    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    # Discordの制限（2000文字）を考慮し、余裕を持って1800文字で分割
    # 箇条書きが途中で崩れないよう、論文1件ごとの区切り（\n\n）で分割を試みる
    blocks = text.split("\n\n")
    chunks = []
    current = ""

    for block in blocks:
        if not block.strip():
            continue
        # ブロック単体で1800文字を超える異常値への対処
        if len(block) > 1800:
            block = block[:1795] + "..."
            
        if len(current) + len(block) + 2 > 1800:
            chunks.append(current.strip())
            current = block + "\n\n"
        else:
            current += block + "\n\n"

    if current:
        chunks.append(current.strip())

    for chunk in chunks:
        while True:
            res = requests.post(webhook, json={"content": chunk})

            if res.status_code == 429:
                # DiscordからのRate Limit通知に対応
                wait = res.json().get("retry_after", 2)
                print(f"Rate limited. Waiting for {wait} seconds...")
                time.sleep(wait)
                continue
            elif res.status_code >= 400:
                print(f"Discord error: {res.status_code} - {res.text}")
                break

            break

        time.sleep(0.5)

    print("Discord send complete")


# -----------------------------
# メイン
# -----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=3)
    parser.add_argument('--output', type=str, default=None)
    parser.add_argument('--discord', type=str, default="https://discord.com/api/webhooks/1504761505151844433/C9Ns2fw9IAjhBcUOnP4TqQ4bwOqnYUUd8WxlDVN1MZ9_R1nd3_3Y7H7HFwEJtCS2voxJ")
    parser.add_argument(
        '--keywords',
        nargs='+',
        default=[
            "active matter", "active nematic", "self-propelled", "phase separation", "flocking", "pattern formation", "swarming","biofluid","macromolecular crowding",
            "collective motion", "actin", "microtubule", "topological defect", "cell motility", "cellular motility", "cytoplasmic streaming", "biological fluid",
            "motor protein", "kinesin", "dynein", "myosin","active Brownian","run-and-tumble","hydrodynamics","self-organization",
            "cytoskeleton", "colloidal", "non-equilibrium", "active suspension", "active fluid", "living matter",
            "active turbulence",
            "active stress",
            "active gel",
            "active phase separation",
            "MIPS",
            "motility-induced phase separation",
            "emergent behavior",
            "self-organization",
            "collective behavior",
            "dense active matter",
            "active liquid crystal",
            "nonequilibrium pattern formation",
            "mechanobiology",
            "cell mechanics",
            "active filament",
            "microtubule network",
            "actomyosin",
            "cytoskeletal dynamics",
            "collective cell migration",
            "epithelium",
            "epithelial mechanics",
            "tissue mechanics",
            "nematic defect",
            "defect dynamics",
            "liquid crystal elastomer",
            "extensile",
            "contractile active matter",
            "actomyosin"

        ]
    )

    args = parser.parse_args()

    print("Start:", datetime.datetime.now())

    target_issns = [
        '1476-4687', '1755-4349', '1745-2481', '2041-1723', '1476-4660', '0027-8424', 
        '2752-6542', '2470-0045', '2160-3308', '0031-9007', '1744-683X', '2375-2548', 
        '1530-6984', '0743-7463', '1936-0851', '2835-8279', '1095-9203', '1549-9626'
    ]

    arxiv_papers = fetch_arxiv(args.keywords, args.days)
    openalex_papers = fetch_openalex(args.keywords, args.days, journal_issns=target_issns)

    papers = arxiv_papers + openalex_papers
    papers = deduplicate(papers)


    papers.sort(key=lambda x: x['date'] or "", reverse=True)


    content = format_markdown(papers, args.keywords)
    filename = args.output or f"papers/daily_{datetime.date.today()}.md"

    save_file(content, filename)

    if args.discord:
        send_discord(filename, args.discord)

    print("Done!")


if __name__ == "__main__":
    main()