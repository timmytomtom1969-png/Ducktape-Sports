import json
import re
import feedparser

def clean_html(text):
    # Removes HTML tags and website link debris so it's pure text for grandpa
    clean = re.compile('<.*?>|&nbsp;|&rlm;|&lrm;')
    text = re.sub(clean, '', text)
    if "Read more" in text:
        text = text.split("Read more")
    return text.strip()

def get_sports_news():
    # Combining feeds to maximize finding local Detroit sports stories
    feed_urls = [
        "https://espn.com",
        "https://cbssports.com"
    ]
    
    detroit_keywords = ['detroit', 'lions', 'tigers', 'pistons', 'red wings', 'michigan wolverines', 'spartans']
    filtered_stories = []
    seen_titles = set()
    
    for url in feed_urls:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get('title', '')
            summary = entry.get('description', entry.get('summary', ''))
            
            if not title or title in seen_titles:
                continue
                
            combined_text = (title + " " + summary).lower()
            if any(keyword in combined_text for keyword in detroit_keywords):
                seen_titles.add(title)
                filtered_stories.append({
                    "title": title,
                    "body": clean_html(summary)
                })
                
    # Fallback: If local teams aren't trending today, fill the rest up with general top sports stories
    if len(filtered_stories) < 6:
        for url in feed_urls:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                if len(filtered_stories) >= 8:
                    break
                title = entry.get('title', '')
                summary = entry.get('description', entry.get('summary', ''))
                
                if title and title not in seen_titles:
                    seen_titles.add(title)
                    filtered_stories.append({
                        "title": title,
                        "body": clean_html(summary)
                    })

    # Save exactly 8 stories to a clean static file in the root directory
    with open('news.json', 'w', encoding='utf-8') as f:
        json.dump(filtered_stories[:8], f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    get_sports_news()
