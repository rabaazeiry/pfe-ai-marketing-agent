# scraper_service.py
# MICROSERVICE PYTHON CRAWL4AI - Inspiré du rapport Sabrine
# Scraping Facebook avec AsyncWebCrawler
# VERSION CORRIGÉE pour Crawl4AI 0.8.6

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup
import re
from datetime import datetime
import asyncio
import os

app = FastAPI(title="Facebook Scraper Crawl4AI")

# ═══════════════════════════════════════════════════════════════════════════
# MODÈLES DE DONNÉES
# ═══════════════════════════════════════════════════════════════════════════

class ScraperConfig(BaseModel):
    url: str
    cssSelectors: Dict[str, str]
    headless: bool = False
    disableCache: bool = True
    scrollCount: int = 25
    waitTime: int = 2000

class Post(BaseModel):
    postUrl: str
    imageUrl: str
    thumbnailUrl: str
    videoUrl: str
    likes: int
    comments: int
    shares: int
    views: int
    caption: str
    contentType: str
    slideCount: int
    hashtags: List[str]
    location: str
    publishedAt: str

class ScraperResponse(BaseModel):
    followers: int
    bio: str
    verified: bool
    posts: List[Post]

# ═══════════════════════════════════════════════════════════════════════════
# FONCTIONS UTILITAIRES
# ═══════════════════════════════════════════════════════════════════════════

def parse_count(text: str) -> int:
    """Parse les nombres avec K, M (ex: 1.5K → 1500)"""
    if not text:
        return 0
    
    text = text.strip().replace(',', '').replace('.', '').replace(' ', '')
    
    # Chercher pattern: nombre suivi de K ou M
    match = re.search(r'(\d+(?:\.\d+)?)\s*([KkMm])?', text)
    if match:
        num = float(match.group(1))
        unit = match.group(2)
        
        if unit and unit.upper() == 'M':
            return int(num * 1000000)
        elif unit and unit.upper() == 'K':
            return int(num * 1000)
        return int(num)
    
    return 0

def extract_hashtags(text: str) -> List[str]:
    """Extrait les hashtags d'un texte"""
    return [match.group(1) for match in re.finditer(r'#(\w+)', text)]

# ═══════════════════════════════════════════════════════════════════════════
# SCRAPER PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/scrape", response_model=ScraperResponse)
async def scrape_facebook(config: ScraperConfig):
    """
    Scrape une page Facebook mobile avec Crawl4AI
    Inspiré du pipeline du rapport Sabrine (LEONI)
    VERSION CORRIGÉE pour Crawl4AI 0.8.6
    """
    
    try:
        print(f"🔍 Scraping: {config.url}")
        
        # ✅ Configuration Crawl4AI (version 0.8.6 - headless retiré)
        crawler_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS if config.disableCache else CacheMode.ENABLED,
            wait_until="networkidle",
            page_timeout=60000,
            
            # JavaScript pour scroll automatique (révéler posts cachés)
            js_code=f"""
            async function scrollPage() {{
                for (let i = 0; i < {config.scrollCount}; i++) {{
                    window.scrollBy(0, 800);
                    await new Promise(r => setTimeout(r, {config.waitTime}));
                }}
            }}
            await scrollPage();
            """,
        )
        
        # ✅ AsyncWebCrawler avec headless passé au crawler (pas au config)
        async with AsyncWebCrawler(headless=config.headless) as crawler:
            print("⏳ Crawl en cours...")
            
            result = await crawler.arun(
                url=config.url,
                config=crawler_config
            )
            
            if not result.success:
                raise HTTPException(status_code=500, detail="Échec du crawling")
            
            print(f"✅ HTML récupéré ({len(result.html)} chars)")
            
            # 🔍 DEBUG : Sauvegarde le HTML pour inspection
            debug_file = os.path.join(os.path.dirname(__file__), "facebook_debug.html")
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(result.html)
            print(f"💾 HTML sauvegardé dans: {debug_file}")
            
            # ✅ Parse HTML avec BeautifulSoup (comme Sabrine)
            soup = BeautifulSoup(result.html, 'html.parser')
            
            # Extraction followers
            followers = 0
            for selector in config.cssSelectors.get('followers', '').split(','):
                elem = soup.select_one(selector.strip())
                if elem:
                    followers = parse_count(elem.get_text())
                    if followers > 0:
                        break
            
            # Extraction posts
            posts = []
            post_selectors = config.cssSelectors.get('posts', '').split(',')
            post_elements = []
            
            for selector in post_selectors:
                post_elements.extend(soup.select(selector.strip()))
                if len(post_elements) >= 20:
                    break
            
            print(f"📊 {len(post_elements)} posts trouvés")
            
            for idx, post_elem in enumerate(post_elements[:20]):
                post_text = post_elem.get_text()
                
                if len(post_text) < 20:
                    continue
                
                # Extraction métriques
                likes = 0
                likes_elem = post_elem.select_one(config.cssSelectors.get('likes', ''))
                if likes_elem:
                    likes = parse_count(likes_elem.get_text())
                
                comments = 0
                comments_match = re.search(r'(\d+)\s*(?:commentaire|comment)', post_text, re.I)
                if comments_match:
                    comments = int(comments_match.group(1))
                
                shares = 0
                shares_match = re.search(r'(\d+)\s*(?:partage|share)', post_text, re.I)
                if shares_match:
                    shares = int(shares_match.group(1))
                
                # Extraction caption
                lines = [l for l in post_text.split('\n') if len(l.strip()) > 10]
                caption = ' '.join(lines[:5])[:500]
                
                # Extraction image
                img_elem = post_elem.select_one(config.cssSelectors.get('image', 'img'))
                image_url = img_elem['src'] if img_elem and 'src' in img_elem.attrs else ''
                
                # Extraction URL post
                link_elem = post_elem.select_one('a[href*="/story"], a[href*="/posts/"]')
                post_url = f"https://m.facebook.com{link_elem['href']}" if link_elem else f"https://m.facebook.com/post_{idx}"
                
                posts.append(Post(
                    postUrl=post_url,
                    imageUrl=image_url,
                    thumbnailUrl=image_url,
                    videoUrl='',
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    views=0,
                    caption=caption,
                    contentType='photo',
                    slideCount=1,
                    hashtags=extract_hashtags(caption),
                    location='',
                    publishedAt=datetime.now().isoformat()
                ))
            
            print(f"✅ {len(posts)} posts extraits")
            
            return ScraperResponse(
                followers=followers,
                bio='',
                verified=False,
                posts=posts
            )
    
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Crawl4AI Facebook Scraper"}

# ═══════════════════════════════════════════════════════════════════════════
# DÉMARRAGE
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("🚀 Démarrage Crawl4AI Scraper Service...")
    print("📍 Endpoint: http://localhost:8000/scrape")
    uvicorn.run(app, host="0.0.0.0", port=8000)