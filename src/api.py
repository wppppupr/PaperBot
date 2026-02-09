import google.generativeai as genai

# あなたのAPIキーを入れてください
genai.configure(api_key="AIzaSyDqnPBa9SLpCj7ygH56PooWQLfGtJVf48o")

print("--- あなたのAPIキーで利用可能なモデル一覧 ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Name: {m.name}")
except Exception as e:
    print(f"エラーが発生しました: {e}")