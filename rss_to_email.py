import feedparser
import html
import argparse
import json
import os
import base64
import bleach
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# Define which HTML tags, attributes, and styles you allow:
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u', 'a',
    'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'h1', 'h2', 'h3',
    'abbr', 'acronym', 'img',
]
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt'],
    'abbr': ['title'], 
    'acronym': ['title'],
}
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']

def get_reading_time_from_text(text):
    """Estimate reading time based on word count (assumes 200 wpm)."""
    words = len(text.split())
    return round(words / 200)

def get_reading_time_from_url(url):
    """Estimate reading time based on word count from the article URL."""
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()
        return get_reading_time_from_text(text)
    except:
        return "Unknown"

def load_seen_articles(filename="seen_articles.json"):
    """
    Load the dictionary of seen articles:
    {
      "feed_url": ["link1", "link2", ...],
      "another_feed_url": [...]
    }
    """
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_seen_articles(seen_articles, filename="seen_articles.json"):
    """Save the dictionary of seen articles."""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(seen_articles, f, indent=2)

def fetch_rss_articles(feed_urls, seen_articles, max_articles_per_feed):
    """
    Fetch articles from multiple RSS feeds and filter out those that are already seen.
    Each feed is tracked separately. We rotate out the oldest link if we exceed the max size.
    """
    articles = []

    for feed_url in feed_urls:
        # Ensure this feed key exists in seen_articles
        if feed_url not in seen_articles:
            seen_articles[feed_url] = []

        feed = feedparser.parse(feed_url)
        feed_domain = urlparse(feed_url).netloc  # Extract domain from feed URL

        new_seen_articles = []
        for entry in feed.entries[:max_articles_per_feed]:
            # Check if we've already seen this link for this feed
            if entry.link in seen_articles[feed_url]:
                # If yes, we assume we've seen all the rest as well
                break

            # Collect full content if available; otherwise, fallback
            content_list = entry.get("content", [])
            content = " ".join(item.get("value", "") for item in content_list).strip()
            description = entry.get("description", "")

            if content:
                soup = BeautifulSoup(content, "html.parser")
                text = soup.get_text()
                reading_time = get_reading_time_from_text(text)
            else:
                reading_time = get_reading_time_from_url(entry.link)

            author = entry.get("author", feed_domain)  # Use domain if no author
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "reading_time": reading_time,
                "author": author,
                "content": content if content else description,
            })

            new_seen_articles.append(entry.link)
        
        # Update seen articles for this feed
        seen_articles[feed_url] = new_seen_articles + seen_articles[feed_url]

        # Limit the number of seen articles per feed
        seen_articles[feed_url] = seen_articles[feed_url][:max_articles_per_feed]

    # Save after processing all feeds
    save_seen_articles(seen_articles)
    return articles

def sanitize_html(input_html: str) -> str:
    """
    Sanitize the given HTML string, allowing only a limited set of tags, 
    attributes, and protocols.
    """
    return bleach.clean(
        input_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True  # remove disallowed tags entirely
    )

def format_email_content(article):
    """Format the email body content."""
    # We escape certain fields that should remain plain text:
    title_html = html.escape(article['title'])
    author_html = html.escape(article['author'])
    
    # We sanitize content HTML, as we want some formatting here
    content_html = ""
    if article.get('content'):
        content_html = sanitize_html(article['content'])

    content = f"<h2>{title_html}</h2>"
    content += f"<p><b>Author:</b> {author_html}<br>"
    content += f"<a href='{article['link']}'>{article['link']}</a><br>"
    content += f"<i>Estimated Reading Time: {article['reading_time']} min</i></p>"
    if article['content']:
        content += f"<div>{content_html}</div>"
    return content

def build_email(to_email, from_email, article):
    """Build the email message."""
    msg = MIMEMultipart()
    msg['From'] = f"{article['author']} <{from_email}>"
    msg['To'] = to_email
    msg['Subject'] = article['title']
    
    email_content = format_email_content(article)
    msg.attach(MIMEText(email_content, 'html'))
    return msg

def send_email_with_gmail_api(to_email, from_email, article):
    """
    Send an email via the Gmail API using OAuth 2.0.
    """
    # 1) Load / refresh credentials
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    # 2) Build the Gmail API service
    service = build('gmail', 'v1', credentials=creds)

    # 3) Build the email message
    msg = build_email(to_email, from_email, article)

    # 4) Encode and send
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body = {'raw': raw}

    try:
        message_sent = service.users().messages().send(userId='me', body=body).execute()
        print(f"Email sent to {to_email}, Message ID: {message_sent['id']}")
    except Exception as e:
        print(f"An error occurred while sending the email: {e}")

def output_to_console(article):
    """Print article information to the console."""
    print("\nTitle:", article['title'])
    print("Author:", article['author'])
    print("Link:", article['link'])
    print("Estimated Reading Time:", article['reading_time'], "min")
    if article['content']:
        print("\nContent:\n", article['content'])
    print("-" * 40)

def append_to_file(filename, article):
    """Append article information to a text file."""
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"Title: {article['title']}\n")
        f.write(f"Author: {article['author']}\n")
        f.write(f"Link: {article['link']}\n")
        f.write(f"Estimated Reading Time: {article['reading_time']} min\n")
        if article['content']:
            f.write(f"\nContent:\n{article['content']}\n")
        f.write("-" * 40 + "\n")

def load_rss_feeds(file_path):
    """Load RSS feed URLs from a text file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch RSS articles and output via email, console, or file.")
    parser.add_argument("--output", choices=["email", "console", "file"], default="console",
                        help="Output format: email, console, or file (default: console)")
    parser.add_argument("--file", type=str, help="File path to append output if using file mode")
    parser.add_argument("--feeds", type=str, required=True,
                        help="Path to a text file containing RSS feed URLs")
    parser.add_argument("--credentials", type=str, default="credentials.json",
                        help="Path to a Gmail API credentials file")
    parser.add_argument("--to_email", type=str, help="Recipient email address")
    parser.add_argument("--from_email", type=str, help="Sender email address")
    parser.add_argument("--max_articles", type=int, default=1,
                        help="Maximum number of links to store and send per feed (default: 1)")
    args = parser.parse_args()

    if args.output == "file" and not args.file:
        parser.error("--file is required when using file output mode")
    if args.output == "email" and not os.path.exists(args.credentials):
        parser.error("--credentials is required when using email output mode")
    if args.output == "email" and not args.to_email:
        parser.error("Recipient email address is required when using email output mode")
    if args.output == "email" and not args.from_email:
        parser.error("Sender email address is required when using email output mode")

    RSS_FEEDS = load_rss_feeds(args.feeds)
    
    # Load the dictionary that keeps seen articles per feed
    seen_articles = load_seen_articles()

    # Fetch new articles, marking them as seen in the dictionary
    articles = fetch_rss_articles(RSS_FEEDS, seen_articles, args.max_articles)

    if articles:
        for article in articles:
            if args.output == "email":
                send_email_with_gmail_api(args.to_email, args.from_email, article)
            elif args.output == "console":
                output_to_console(article)
            elif args.output == "file" and args.file:
                append_to_file(args.file, article)
