import requests
import argparse

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
