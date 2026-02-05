#!/usr/bin/env python3
import os, sys, time, logging, argparse
from datetime import datetime
from typing import List, Dict
import requests, schedule
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import smtplib
import yaml

# Load config from environment variables (for cloud) or config.yaml (local)
def load_config():
    if os.environ.get('EMAIL_SENDER'):
        return {
            'email': {
                'smtp_server': 'smtp.gmail.com',
                'smtp_port': 587,
                'sender_email': os.environ.get('EMAIL_SENDER'),
                'sender_password': os.environ.get('EMAIL_PASSWORD'),
                'recipient_email': os.environ.get('EMAIL_RECIPIENT')
            },
            'news': {
                'api_key': os.environ.get('NEWS_API_KEY'),
                'categories': ['technology', 'business', 'science', 'health', 'national', 'international', 'education', 'environment'],
                'country': 'in',
                'articles_per_category': 4
            },
            'scheduler': {
                'time': os.environ.get('SCHEDULER_TIME', '07:00')
            }
        }
    with open('config.yaml', 'r') as f:
        return yaml.safe_load(f)

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout)])
    return logging.getLogger(__name__)

class NewsFetcher:
    def __init__(self, api_key, logger):
        self.api_key, self.logger = api_key, logger
        self.base_url = "https://newsapi.org/v2"
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'NewsBot/1.0'})
    
    def search_news(self, query):
        url = f"{self.base_url}/everything"
        params = {'apiKey': self.api_key, 'q': query, 'language': 'en', 
                  'sortBy': 'publishedAt', 'pageSize': 8}
        try:
            response = self.session.get(url, params=params, timeout=30)
            data = response.json()
            if data.get('status') == 'ok':
                articles = [a for a in data.get('articles', []) 
                           if a.get('title') and a['title'] != '[Removed]']
                return articles[:6]
            return []
        except Exception as e:
            self.logger.error(f"Error: {e}")
            return []

class NewsSummarizer:
    @staticmethod
    def clean_text(text, max_len=150):
        if not text:
            return "No details available"
        text = ' '.join(text.split())[:max_len]
        return text if len(text) < max_len else text.rsplit(' ', 1)[0] + '...'
    
    @classmethod
    def create_summary(cls, article):
        return {
            'title': article.get('title', 'No Title')[:100],
            'summary': cls.clean_text(article.get('description', ''), 150),
            'source': article.get('source', {}).get('name', 'Unknown'),
            'url': article.get('url', '')
        }

class EmailSender:
    def __init__(self, config, logger):
        self.logger = logger
        self.smtp_server, self.smtp_port = config['smtp_server'], config['smtp_port']
        self.sender_email, self.sender_password = config['sender_email'], config['sender_password']
        self.recipient_email = config['recipient_email']
    
    def create_email(self, news_data, date_str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>Daily News</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f7fa;padding:15px}}
.container{{max-width:680px;margin:0 auto}}
.header{{background:linear-gradient(135deg,#1e3c72,#2a5298);color:white;padding:30px;border-radius:16px;text-align:center;margin-bottom:20px}}
.category{{background:white;border-radius:12px;padding:20px;margin-bottom:18px;box-shadow:0 2px 8px rgba(0,0,0,0.06)}}
.cat-header{{display:flex;align-items:center;margin-bottom:15px;padding-bottom:12px;border-bottom:2px solid #f0f2f5}}
.cat-icon{{font-size:26px;margin-right:12px}}
.cat-title{{font-size:18px;font-weight:700;color:#1e3c72}}
.news-item{{padding:14px 0;border-bottom:1px solid #f0f0f0}}
.news-title{{font-size:15px;font-weight:600;margin-bottom:6px}}
.news-title a{{color:#2a5298;text-decoration:none}}
.news-source{{font-size:12px;color:#888;margin-bottom:8px}}
.news-summary{{font-size:14px;color:#555;background:#f8f9fa;padding:12px;border-radius:8px;border-left:3px solid #2a5298}}
.read-btn{{display:inline-block;margin-top:8px;font-size:13px;color:#2a5298;text-decoration:none;font-weight:500}}
.stats{{background:#e8f4fd;padding:12px;border-radius:8px;text-align:center;margin-bottom:20px;font-size:14px;color:#1e3c72}}
</style></head><body><div class='container'>
<div class='header'><h1>📰 Your Daily News Briefing</h1><p>{date_str} • Easy to understand</p></div>"""
        
        cat_info = {
            'national': ('📰', 'NATIONAL (INDIA)', 'Govt schemes, laws, policies'),
            'international': ('🌍', 'INTERNATIONAL', 'Global news, India relations'),
            'economy': ('💰', 'ECONOMY & BUSINESS', 'Money, markets, companies'),
            'science': ('📈', 'SCIENCE & TECH', 'AI, space, inventions'),
            'education': ('🎓', 'EDUCATION & EXAMS', 'Exams, results, admissions'),
            'environment': ('🌱', 'ENVIRONMENT', 'Climate, disasters'),
            'technology': ('📊', 'TECHNOLOGY', 'Tech news, AI'),
            'health': ('🏥', 'HEALTH', 'Medical, wellness')
        }
        
        total = 0
        for cat_key, (emoji, name, _) in cat_info.items():
            articles = news_data.get(cat_key, [])
            if not articles:
                continue
            total += len(articles)
            html += f'<div class="category"><div class="cat-header"><span class="cat-icon">{emoji}</span><span class="cat-title">{name}</span></div>'
            for news in articles:
                title, summary, source, url = news.get('title',''), news.get('summary',''), news.get('source',''), news.get('url','')
                html += f'<div class="news-item"><div class="news-title"><a href="{url}" target="_blank">{title}</a></div><div class="news-source">📰 {source}</div><div class="news-summary">{summary}</div><a href="{url}" class="read-btn" target="_blank">→ Read full article</a></div>'
            html += '</div>'
        
        html += f"<div class='stats'>📊 {total} stories from {len([k for k,v in news_data.items() if v])} categories</div></div></body></html>"
        
        text = f"📰 DAILY NEWS - {date_str}\n{'='*50}\n\n"
        for cat_key, (emoji, name, _) in cat_info.items():
            articles = news_data.get(cat_key, [])
            if articles:
                text += f"{emoji} {name}\n" + "─"*40 + "\n"
                for i, news in enumerate(articles, 1):
                    text += f"{i}. {news.get('title','')}\n   📝 {news.get('summary','')}\n   🔗 {news.get('url','')[:40]}...\n\n"
        text += f"{'='*50}\n🔄 Auto-generated | {total} stories"
        
        return text, html
    
    def send(self, subject, text, html):
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'], msg['From'], msg['To'] = subject, formataddr(['📰 Daily News', self.sender_email]), self.recipient_email
            msg.attach(MIMEText(text, 'plain', 'utf-8'))
            msg.attach(MIMEText(html, 'html', 'utf-8'))
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)
            self.logger.info("✅ Email sent!")
            return True
        except Exception as e:
            self.logger.error(f"❌ Error: {e}")
            return False

class NewsAutomator:
    TOPICS = {
        'national': ['India government scheme', 'Parliament law India', 'Supreme Court India judgment', 'NEP education India'],
        'international': ['global news India', 'India foreign relations', 'UN WHO India'],
        'economy': ['India economy', 'RBI inflation India', 'stock market India', 'company news India', 'budget India'],
        'technology': ['AI technology India', 'ISRO mission', 'cybersecurity India', 'tech news India'],
        'science': ['scientific discovery', 'space mission', 'research breakthrough'],
        'health': ['health news India', 'medical breakthrough', 'disease outbreak'],
        'education': ['JEE NEET 2024', 'UPSC exam', 'board exam result India', 'scholarship India'],
        'environment': ['climate change India', 'cyclone flood India', 'environment policy India']
    }
    
    def __init__(self):
        self.logger = setup_logging()
        self.config = load_config()
        self.fetcher = NewsFetcher(self.config['news']['api_key'], self.logger)
    
    def fetch_all_news(self):
        news_data = {}
        for cat_key, queries in self.TOPICS.items():
            all_articles = []
            for query in queries:
                articles = self.fetcher.search_news(query)
                all_articles.extend(articles)
                time.sleep(0.5)
            seen_urls = set()
            unique_articles = []
            for art in all_articles:
                url = art.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    unique_articles.append(art)
            news_data[cat_key] = [NewsSummarizer.create_summary(a) for a in unique_articles[:4]]
        return news_data
    
    def run(self):
        self.logger.info("🚀 Fetching and sending news...")
        date_str = datetime.now().strftime("%B %d, %Y")
        news_data = self.fetch_all_news()
        total = sum(len(a) for a in news_data.values())
        if total == 0:
            self.logger.warning("⚠️ No news found")
            return False
        email_sender = EmailSender(self.config['email'], self.logger)
        text, html = email_sender.create_email(news_data, date_str)
        success = email_sender.send(f"📰 Daily News - {date_str} ({total} updates)", text, html)
        self.logger.info(f"✅ Done! Sent {total} articles")
        return success
    
    def scheduler(self):
        schedule_time = self.config['scheduler'].get('time', '07:00')
        self.logger.info(f"⏰ Scheduler ready. Daily at {schedule_time}")
        schedule.every().day.at(schedule_time).do(self.run)
        while True:
            schedule.run_pending()
            time.sleep(30)

def main():
    parser = argparse.ArgumentParser(description='📰 Daily News Bot')
    parser.add_argument('--run-now', action='store_true')
    args = parser.parse_args()
    try:
        bot = NewsAutomator()
        bot.run() if args.run_now else bot.scheduler()
    except KeyboardInterrupt:
        print("\n👋 Stopped")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
          
