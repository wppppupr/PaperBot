import os
import argparse
from simple_paper_bot import send_to_discord

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default='papers/Active_Matter_Review_2026-05-15.md', help="Markdown file to send")
    parser.add_argument('--discord_webhook', type=str, default="https://discord.com/api/webhooks/1504761505151844433/C9Ns2fw9IAjhBcUOnP4TqQ4bwOqnYUUd8WxlDVN1MZ9_R1nd3_3Y7H7HFwEJtCS2voxJ", help="Discord Webhook URL")
    
    args = parser.parse_args()
    
    if os.path.exists(args.file):
        print(f"Sending {args.file} to Discord...")
        send_to_discord(args.file, args.discord_webhook)
    else:
        print(f"File not found: {args.file}")
