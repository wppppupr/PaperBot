import requests
import argparse

DISCORD_ERROR = 'https://discord.com/api/webhooks/1505023099492372672/tcsWs9KogPc0J6tSleMws5OXvndX0CIOSibVkl8khUuNNSIl-pA8J3KP0BFNLvkmBTdF'

def send_hello(webhook_url):
    response = requests.post(webhook_url, json={'content': 'hello'})
    if response.status_code in [200, 204]:
        print("Successfully sent 'hello' to Discord!")
    else:
        print(f"Failed to send. Status code: {response.status_code}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--discord_webhook', type=str, default="https://discord.com/api/webhooks/1504761505151844433/C9Ns2fw9IAjhBcUOnP4TqQ4bwOqnYUUd8WxlDVN1MZ9_R1nd3_3Y7H7HFwEJtCS2voxJ", help="Discord Webhook URL")
    
    args = parser.parse_args()
    send_hello(args.discord_webhook)


    try:
        a=1/0        
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
        try:
            requests.post(DISCORD_ERROR, json={'content': discord_error_text})
            print("Error notification sent to Discord.")
        except Exception as send_err:
            print(f"Failed to send error notification to Discord: {send_err}")