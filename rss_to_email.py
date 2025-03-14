import feedparser
import smtplib
import html
import argparse
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Adjust this to whatever maximum number of links you want to store per feed
MAX_LINKS_PER_FEED = 5

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

def fetch_rss_articles(feed_urls, seen_articles):
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
        for entry in feed.entries[:MAX_LINKS_PER_FEED]:
            # Check if we've already seen this link for this feed
            if entry.link in seen_articles[feed_url]:
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
        seen_articles[feed_url] = seen_articles[feed_url][:MAX_LINKS_PER_FEED]

    # Save after processing all feeds
    save_seen_articles(seen_articles)
    return articles

def format_email_content(article):
    """Format the email body content."""
    content = f"<h2>{html.escape(article['title'])}</h2>"
    content += f"<p><b>Author:</b> {html.escape(article['author'])}<br>"
    content += f"<a href='{article['link']}'>{article['link']}</a><br>"
    content += f"Estimated Reading Time: {article['reading_time']} min</p>"
    if article['content']:
        content += f"<p>{html.escape(article['content'])}</p>"
    return content

def send_email(to_email, from_email, smtp_server, smtp_port, smtp_user, smtp_pass, article):
    """Send an individual email per article."""
    msg = MIMEMultipart()
    msg['From'] = f"{article['author']} <{from_email}>"
    msg['To'] = to_email
    msg['Subject'] = article['title']
    
    email_content = format_email_content(article)
    msg.attach(MIMEText(email_content, 'html'))
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, to_email, msg.as_string())

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
    parser.add_argument("--rss_file", type=str, required=True,
                        help="Path to the text file containing RSS feed URLs")
    args = parser.parse_args()

    RSS_FEEDS = load_rss_feeds(args.rss_file)
    TO_EMAIL = "your_email@example.com"
    FROM_EMAIL = "your_smtp_email@example.com"
    SMTP_SERVER = "smtp.example.com"
    SMTP_PORT = 587
    SMTP_USER = "your_smtp_email@example.com"
    SMTP_PASS = "your_smtp_password"
    
    # Load the dictionary that keeps seen articles per feed
    seen_articles = load_seen_articles()
    # Fetch new articles, marking them as seen in the dictionary
    articles = fetch_rss_articles(RSS_FEEDS, seen_articles)

    if articles:
        for article in articles:
            if args.output == "email":
                send_email(TO_EMAIL, FROM_EMAIL, SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, article)
            elif args.output == "console":
                output_to_console(article)
            elif args.output == "file" and args.file:
                append_to_file(args.file, article)
