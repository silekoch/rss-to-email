# RSS to Email Notifier

This Python script fetches articles from specified RSS feeds and sends them via email using the **Gmail API** (OAuth2 authentication). It also supports outputting articles to the console for debugging. The script can be **automated** on macOS using a `launchd` job and provides a setup routine to generate the necessary plist file.

---

## Features

- Fetch new articles from **multiple RSS feeds**.
- **Avoids duplicate articles** by tracking previously sent links.
- **Estimates reading time** for each article.
- **Sends emails via Gmail API** (OAuth2) with formatted HTML content.
- **Sanitizes HTML** content to avoid security risks.
- Can be **automated** via a `launchd` background job on macOS.
- Supports **setup mode** (`--setup`) to configure and generate a `launchd` plist file and run the initial interactive authentication with Gmail.

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/silekoch/rss-to-email.git
cd rss_to_email
```

### 2. Install Dependencies
This script requires Python 3.7+ and the following libraries:

```bash
pip install -r requirements.txt
```
Alternatively, install them manually:

```bash
pip install feedparser requests beautifulsoup4 google-auth-oauthlib google-auth-httplib2 google-api-python-client bleach
```

## Usage

### 1. Prepare a List of RSS Feeds
Create a plain text file (e.g., feeds.txt) with one RSS feed URL per line:

```
# feeds.txt
https://example.com/rss
https://anotherexample.com/feed
```
### 2. Run the Script Manually
Fetch and display articles in the console

```bash
python rss_to_email.py feeds.txt --output console
```

Fetch and send articles via email

```
python rss_to_email.py feeds.txt \
  --output email \
  --to_email your_recipient@example.com \
  --from_email your_gmail@example.com \
  --credentials credentials.json \
  --app_data_dir /Users/yourusername/Library/Application\ Support/rss_to_email/
```

## First-Time Setup (OAuth + Automation)

Before running the script on a schedule, you need to authenticate with Gmail and set up automation.

### 1. Authenticate Gmail API (OAuth2)
This script uses the Gmail API for sending emails. You need to set up OAuth2 credentials:

#### Step 1: Enable Gmail API

Visit the Google Cloud Console
Create a project and enable the Gmail API.
Navigate to APIs & Services > Credentials and create an OAuth 2.0 Client ID.
Choose "Desktop App" as the application type.
Download the credentials JSON file (credentials.json) and place it in the script directory.

#### Step 2: Run the Setup Mode

This will:

- Authenticate your Gmail account (opens a browser for sign-in).
- Generate the necessary token.json for API authentication.
- Create a `launchd` job to automate the script.

```
python rss_to_email.py 
  --setup \
  --feeds feeds.txt \
  --to_email your_recipient@example.com \
  --from_email your_gmail@example.com \
  --credentials credentials.json \
  --interval 10800 \
  --app_data_dir /Users/yourusername/Library/Application\ Support/rss_to_email/
```

### Automating with `launchd` (macOS)

#### 1. Generate a `launchd` Job
The --setup command above automatically creates a macOS `launchd` plist file at:

```
~/Library/LaunchAgents/com.rss_to_email.plist
```

#### 2. Load the Job into `launchd`
```
launchctl load ~/Library/LaunchAgents/com.rss_to_email.plist
launchctl start com.rss_to_email
```

#### 3. Verify It’s Running
```
launchctl list | grep rss_to_email
```

#### 4. Manually Stop or Remove the Job
```
launchctl unload ~/Library/LaunchAgents/com.rss_to_email.plist
```

## Configuration Options

| Flag | Description |
| --- | --- |
| feeds | Path to RSS feeds file (required). |
| --output | email or console (default: console). |
| --to_email | Recipient email address. |
| --from_email | Sender Gmail address. |
| --credentials | Path to the Gmail API credentials file (credentials.json). |
| --max_articles | Max articles per feed (default: 1). |
| --interval | How often to run (seconds, default: 10800 = 3 hours). |
| --setup | Runs the setup process (OAuth + automation). |
| --app_data_dir | Path to a writable directory for saving logs and seen articles. |

## Logs and Data Storage

The script stores previously seen articles in:
```
~/Library/Application Support/rss_to_email/seen_articles.json
```

Log files:
```
~/Library/Application Support/rss_to_email/rss_to_email.log
~/Library/Application Support/rss_to_email/rss_to_email_error.log
```


## Security & Privacy Considerations

- The script sanitizes HTML before sending to prevent malicious code injection.
- OAuth tokens (token.json) are stored locally and should not be shared.
- External images in emails may leak tracking information (can be disabled in email clients).
- If running on a shared machine, make sure permissions on token.json and credentials.json are restricted (chmod 600).

## Troubleshooting

1. OSError: [Errno 30] Read-only file system: 'seen_articles.json'
Ensure --app_data_dir is set to a writable directory, like:
--app_data_dir /Users/yourusername/Library/Application\ Support/rss_to_email/
2. Gmail API Errors (Unauthorized / Expired Token)
If the OAuth token expires or gets revoked, delete token.json and re-run:
python rss_to_email.py --setup
3. `launchd` Job Doesn't Run
Ensure the plist is loaded:
launchctl list | grep rss_to_email
Check logs:
cat ~/Library/Application\ Support/rss_to_email/rss_to_email_error.log
If still not working, try reloading:
launchctl unload ~/Library/LaunchAgents/com.rss_to_email.plist
launchctl load ~/Library/LaunchAgents/com.rss_to_email.plist


## License

MIT License. Feel free to modify and improve!

## Credits

Thanks to ChatGPT for ample support.
