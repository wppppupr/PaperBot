import datetime
import arxiv
import requests
import time
import argparse
import os
import re

# -----------------------------
# 設定
# -----------------------------
ARXIV_PAGE_SIZE = 50
OPENALEX_MAILER = os.getenv("OPENALEX_MAILER", "your-email@example.com")  # Polite pool用

# -----------------------------
# arXiv取得
# -----------------------------
def fetch_arxiv(keywords, days):
    print("Fetching from arXiv...")
    
    # タイムゾーンに依存しないようUTCで計算（arXivの基準に合わせる）
    target_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    
    # 検索クエリの構築
    keywords_query = " OR ".join([f'all:"{k}"' for k in keywords])
    # 日付はフィルター側で厳密に処理するため、クエリはキーワードを主軸にする
    query = " OR ".join(keywords)

    client = arxiv.Client(page_size=ARXIV_PAGE_SIZE, delay_seconds=2)
    # 過去数日分の論文を網羅するため、max_resultsは少し多めに設定
    search = arxiv.Search(query=query, max_results=200, sort_by=arxiv.SortCriterion.SubmittedDate)

    papers = []
    try:
        for r in client.results(search):
            # 提出日（または更新日）がターゲットより古い場合はスキップ
            # arxivライブラリのr.updatedはタイムゾーン付き(UTC)のため比較可能
            if r.updated < target_date:
                break
                
            papers.append({
                "title": r.title,
                "authors": [a.name for a in r.authors],
                "date": r.updated.strftime('%Y-%m-%d'),
                "url": r.entry_id,
                "source": "arXiv"
            })
    except Exception as e:
        print(f"arXiv error: {e}")

    #papers.sort(key=lambda x: x['date'] or "", reverse=True)

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
    query = " OR ".join(keywords)

    url = "https://api.openalex.org/works"
    headers = {"User-Agent": f"PaperNotifier/1.0 (mailto:{OPENALEX_MAILER})"}
    papers = []

    filter_str = f"from_publication_date:{last_day}"
    if journal_issns:
        journals_filter = "|".join(journal_issns)
        filter_str += f",primary_location.source.issn:{journals_filter}"

    for page in range(1, 4):
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
            abstract = p['abstract'][:150].replace("\n", " ")
            content += f"  - {abstract}...\n"



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
            content += f"  - {p['abstract'][:150]}...\n"


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
    parser.add_argument('--days', type=int, default=1)
    parser.add_argument('--output', type=str, default=None)
    parser.add_argument('--discord', type=str, default="https://discord.com/api/webhooks/1504761505151844433/C9Ns2fw9IAjhBcUOnP4TqQ4bwOqnYUUd8WxlDVN1MZ9_R1nd3_3Y7H7HFwEJtCS2voxJ")
    parser.add_argument(
        '--keywords',
        nargs='+',
        default=[
            "active matter", "active nematic", "self-propelled",
            "collective motion", "actin", "microtubule",
            "motor protein", "kinesin", "dynein", "myosin",
            "cytoskeleton", "colloidal", "non-equilibrium", "active suspension", "active fluid", "living matter"
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