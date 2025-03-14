import feedparser
import html
import argparse
import json
import os
import base64
import bleach
import requests
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from textwrap import dedent

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

def obtain_gmail_credentials(credentials_file="credentials.json"):
    """Obtain Gmail API credentials interactively."""
    flow = InstalledAppFlow.from_client_secrets_file(
                credentials_file, SCOPES
            )
    creds = flow.run_local_server(port=0)
    return creds

def send_email_with_gmail_api(to_email, from_email, article, credentials_file="credentials.json"):
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
            creds = obtain_gmail_credentials(credentials_file)
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
        logging.info(f"Email sent to {to_email}, Message ID: {message_sent['id']}")
    except Exception as e:
        logging.error(f"An error occurred while sending the email: {e}")

def output_to_console(article):
    """Print article information to the console."""
    print("\nTitle:", article['title'])
    print("Author:", article['author'])
    print("Link:", article['link'])
    print("Estimated Reading Time:", article['reading_time'], "min")
    if article['content']:
        print("\nContent:\n", article['content'])
    print("-" * 40)

def load_rss_feeds(file_path):
    """Load RSS feed URLs from a text file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def create_plist_content(
    python_path,
    script_path,
    feeds_path,
    to_email,
    from_email,
    max_articles,
    interval,
    log_file,
    error_log_file
):
    """
    Return the content of the plist as a string, inserting the user-specified or default values
    into the plist template.
    """
    # We'll store the final .plist text in a multi-line string template.
    # Use triple-quoted string or dedent for readability:
    plist_template = dedent(f"""
    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" 
             "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
      <dict>
        <!-- Label: unique identifier for this task -->
        <key>Label</key>
        <string>com.rss_to_email</string>

        <!-- ProgramArguments: the Python interpreter + path to your script + any args -->
        <key>ProgramArguments</key>
        <array>
          <string>{python_path}</string>
          <string>{script_path}</string>

          <string>--feeds</string>
          <string>{feeds_path}</string>

          <string>--output</string>
          <string>email</string>

          <string>--to_email</string>
          <string>{to_email}</string>

          <string>--from_email</string>
          <string>{from_email}</string>

          <string>--max_articles</string>
          <string>{max_articles}</string>
        </array>

        <!-- StartInterval is in seconds (default: {interval} seconds) -->
        <key>StartInterval</key>
        <integer>{interval}</integer>

        <!-- KeepAlive false means it won't stay running as a daemon,
             but rather launch periodically based on StartInterval. -->
        <key>KeepAlive</key>
        <false/>

        <!-- If your script writes logs, direct them here (optional) -->
        <key>StandardOutPath</key>
        <string>{log_file}</string>
        <key>StandardErrorPath</key>
        <string>{error_log_file}</string>
      </dict>
    </plist>
    """).strip()
    return plist_template

def setup_mode(args):
    """
    This function runs if --setup is provided.
    It:
    1) Asks the user (or uses defaults) for the relevant paths and intervals.
    2) Writes out a .plist file to ~/Library/LaunchAgents or a user-specified location.
    3) Runs the Gmail API OAuth flow to obtain & save credentials.
    """
    # 1) Gather arguments or prompt user if needed:
    python_path = args.python_path or input("Enter the path to the Python binary: ")
    script_path = args.script_path or str(Path(__file__).absolute())
    script_dir = str(Path(script_path).parent)
    feeds_path = args.feeds or os.path.join(script_dir, "feeds.txt")
    to_email = args.to_email or input("Enter the recipient email address: ")
    from_email = args.from_email or input("Enter the sender email address: ")

    # Where do we store the logs? By default, same directory as script, or user can override
    log_file = os.path.join(script_dir, "rss_to_email.log")
    error_log_file = os.path.join(script_dir, "rss_to_email_error.log")

    # 2) Create the plist content
    plist_content = create_plist_content(
        python_path=python_path,
        script_path=script_path,
        feeds_path=feeds_path,
        to_email=to_email,
        from_email=from_email,
        max_articles=args.max_articles,
        interval=args.interval,
        log_file=log_file,
        error_log_file=error_log_file
    )

    # 3) Decide where to store the .plist; typical location: ~/Library/LaunchAgents/
    home_dir = Path.home()
    launch_agents_dir = home_dir / "Library" / "LaunchAgents"
    plist_path = launch_agents_dir / "com.rss_to_email.plist"

    # Ensure the LaunchAgents directory exists
    launch_agents_dir.mkdir(parents=True, exist_ok=True)

    # 4) Write the plist file
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(plist_content + "\n")

    print(f"Launch Agent plist created at: {plist_path}")
    print("You can load it with:")
    print(f"    launchctl load {plist_path}")
    print("And to start it immediately:")
    print(f"    launchctl start com.rss_to_email")

    # 5) Run Gmail API OAuth flow and save token.json
    #    (Ensure you have credentials.json in the same directory or specify path if needed)
    print("\nObtaining Gmail credentials. A browser window may open for sign-in...\n")
    creds = obtain_gmail_credentials(credentials_file="credentials.json")
    with open("token.json", "w") as token_file:
        token_file.write(creds.to_json())
    print("token.json created successfully. Setup is complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch RSS articles and output via email, console, or file.")
    parser.add_argument("feeds", type=str,
                        help="Path to a text file containing RSS feed URLs")
    parser.add_argument("--output", choices=["email", "console", "file"], default="console",
                        help="Output format: email, console, or file (default: console)")
    parser.add_argument("--max_articles", type=int, default=1,
                        help="Maximum number of links to store and send per feed (default: 1)")
    parser.add_argument("--credentials", type=str, default="credentials.json",
                        help="Path to a Gmail API credentials file")
    parser.add_argument("--to_email", type=str, help="Recipient email address")
    parser.add_argument("--from_email", type=str, help="Sender email address")
    parser.add_argument("--setup", action="store_true", help="Run the Gmail API setup flow and generate a plist according to the arguments")
    parser.add_argument("--interval", type=str, default=10800,
                        help="How often to run (in seconds) if generating a launchd plist. (default 10800 = 3 hours)")
    parser.add_argument("--python_path", type=str, default=None,
                        help="Path to python binary (if generating a launchd plist).")
    parser.add_argument("--script_path", type=str, default=None,
                        help="Path to this script (if generating a launchd plist).")

    args = parser.parse_args()

    # If setup mode is requested, do that and then exit
    if args.setup:
        setup_mode(args)
        exit()

    if args.output == "email" and not os.path.exists(args.credentials):
        parser.error("--credentials is required when using email output mode")
    if args.output == "email" and not args.to_email:
        parser.error("Recipient email address is required when using email output mode")
    if args.output == "email" and not args.from_email:
        parser.error("Sender email address is required when using email output mode")

    logging.basicConfig(level=logging.INFO)

    RSS_FEEDS = load_rss_feeds(args.feeds)
    
    # Load the dictionary that keeps seen articles per feed
    seen_articles = load_seen_articles()

    # Fetch new articles, marking them as seen in the dictionary
    articles = fetch_rss_articles(RSS_FEEDS, seen_articles, args.max_articles)

    if articles:
        for article in articles:
            if args.output == "email":
                send_email_with_gmail_api(args.to_email, args.from_email, article, args.credentials)
            elif args.output == "console":
                output_to_console(article)
