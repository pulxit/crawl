import streamlit as st
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin, urlparse
import json
import asyncio

# LLM API integration using groq
from groq import Groq

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType

# Create a global groq client instance
groq_client = Groq()


def fetch_category_page_content(url):
    """
    Uses headless Selenium to fetch a category page with dynamic JS-rendered
    content, handling infinite scrolling until no new content is loaded.
    """
    try:
        options = Options()
        # Headless and extra options for a containerized/cloud environment.
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        # Use ChromeDriverManager to auto-install the correct driver for Chromium.
        service = Service(
            ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()
        )
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.get(url)
        # Initial wait for content to load.
        time.sleep(3)
        scroll_pause_time = 3
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        while scroll_count < 10:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause_time)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_count += 1
        content = driver.page_source
        driver.quit()
        return content
    except Exception as e:
        print(f"Infinite scrolling fetch failed for {url}: {e}")
    return ""


def determine_link_type(a_tag):
    """
    Analyzes an <a> element to decide if it likely points to a product page.
    
    Returns a tuple:
        (direct_product: bool, ambiguous: bool, context_snippet: str)
    """
    href = a_tag.get("href")
    if not href:
        return (False, False, "")
    direct_product = False
    ambiguous = False
    product_keywords = ['product', 'item']

    # Check for direct URL patterns.
    for keyword in product_keywords:
        if re.search(rf"/{keyword}/", href):
            direct_product = True

    # Check parent element classes.
    parent = a_tag.parent
    if parent and parent.has_attr("class"):
        parent_classes = " ".join(parent["class"])
        if "product-card" in parent_classes or "product" in parent_classes or "item" in parent_classes:
            direct_product = True

    # Check anchor text for price or "Add to Cart".
    anchor_text = a_tag.get_text().strip()
    if re.search(r"\$\d+", anchor_text) or "add to cart" in anchor_text.lower():
        direct_product = True

    if parent:
        parent_text = parent.get_text(separator=" ", strip=True)
        if re.search(r"\$\d+", parent_text) or "add to cart" in parent_text.lower():
            direct_product = True

    # Mark ambiguous if no high-confidence signal but product keywords exist.
    if not direct_product and any(kw in href for kw in product_keywords):
        ambiguous = True

    # Use parent's text as context (truncated to 200 characters)
    context_snippet = parent.get_text(separator=" ", strip=True)[:200] if parent else ""
    return (direct_product, ambiguous, context_snippet)


def is_internal_url(url, base_netloc):
    """
    Checks if the URL is internal based on the base domain netloc.
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc == "" or parsed.netloc == base_netloc:
            return True
        # Also consider subdomains as internal.
        if parsed.netloc.endswith(base_netloc):
            return True
    except Exception:
        pass
    return False


def validate_links_with_llm(batch):
    """
    Given a batch of ambiguous links (each a tuple of (url, context)), 
    send them to the LLM API (via groq) for product page validation.
    Returns a list of verdicts ("YES" or "NO") corresponding to the batch.
    """
    prompt_lines = [
        "Determine if these links point to product pages. Reply 'YES' or 'NO' for each:"
    ]
    for idx, (link, context) in enumerate(batch, start=1):
        prompt_lines.append(f"{idx}. Link: {link} | Context: {context}")
    prompt_message = "\n".join(prompt_lines)
    try:
        print(f"INFO: Making LLM API call with batch size {len(batch)}")
        messages = [{"role": "user", "content": prompt_message}]
        completion = groq_client.chat.completions.create(
            model="deepseek-r1-distill-llama-70b",
            messages=messages,
            temperature=0.6,
            max_completion_tokens=1024,
            top_p=0.95,
            stream=True,
            reasoning_format="raw"
        )
        response = ""
        for chunk in completion:
            response += chunk.choices[0].delta.content or ""
    except Exception as e:
        print("LLM API call failed:", e)
        response = ""
    
    verdicts = []
    for line in response.splitlines():
        line_clean = line.strip().upper()
        if "YES" in line_clean:
            verdicts.append("YES")
        elif "NO" in line_clean:
            verdicts.append("NO")
    if len(verdicts) < len(batch):
        verdicts.extend(["NO"] * (len(batch) - len(verdicts)))
    return verdicts


def crawl_category_page(url):
    """
    Crawls a given category page URL to find product URLs.
    Applies both direct heuristics and LLM-batched validation for ambiguous links.
    """
    print(f"Crawling category page: {url}")
    
    category_url = url if url.startswith("http") else "http://" + url
    parsed_base = urlparse(category_url)
    base_netloc = parsed_base.netloc
    
    visited = set()
    to_visit = [(category_url, 0)]
    max_depth = 0
    product_urls = set()
    ambiguous_links = []
    
    while to_visit:
        current_url, depth = to_visit.pop(0)
        if current_url in visited or depth > max_depth:
            continue
        visited.add(current_url)
        print(f"Fetching: {current_url} (depth {depth})")
        content = fetch_category_page_content(current_url)
        if not content:
            continue
        
        soup = BeautifulSoup(content, "html.parser")
        a_tags = soup.find_all("a", href=True)
        for a in a_tags:
            href = a["href"]
            absolute_url = urljoin(current_url, href)
            if not is_internal_url(absolute_url, base_netloc):
                continue
            
            direct, ambiguous, context = determine_link_type(a)
            if direct:
                product_urls.add(absolute_url)
            elif ambiguous:
                ambiguous_links.append((absolute_url, context))
            
            if absolute_url not in visited and depth < max_depth:
                to_visit.append((absolute_url, depth + 1))
        
    # Process ambiguous links in batches.
    batch_size = 10
    for i in range(0, len(ambiguous_links), batch_size):
        batch = ambiguous_links[i : i + batch_size]
        verdicts = validate_links_with_llm(batch)
        for (link, _), verdict in zip(batch, verdicts):
            if verdict.upper() == "YES":
                product_urls.add(link)
    
    return list(product_urls)


async def async_crawl_category_page(url):
    return await asyncio.to_thread(crawl_category_page, url)


# ---------------------------------------------------------------------------------
# Streamlit App Interface
# ---------------------------------------------------------------------------------
def streamlit_app():
    st.title("SPIDER 🕷️: Scalable Product Identification and Discovery for Ecommerce Reconnaissance")
    st.markdown("""
    **Instructions:**
    - Enter one or more category URLs (one per line) below.
    - Category URLs should be pages that list products, such as a product category, search results, or collection pages.
    - Click **Crawl** to begin.
    """)
    
    input_text = st.text_area("Enter category URLs (one per line)", height=150)
    
    if st.button("Crawl"):
        if input_text.strip() == "":
            st.warning("Please enter at least one URL.")
        else:
            category_urls = [line.strip() for line in input_text.splitlines() if line.strip()]
            results = {}
            progress_bar = st.progress(0)
            for i, url in enumerate(category_urls):
                with st.spinner(f"Crawling {url} ..."):
                    product_links = crawl_category_page(url)
                    results[url] = product_links
                progress_bar.progress((i + 1) / len(category_urls))
            st.success("Crawling complete!")
            st.subheader("Crawl Results:")
            st.json(results)
            
            json_results = json.dumps(results, indent=4)
            st.download_button("Download JSON results", data=json_results, file_name="crawl_results.json", mime="application/json")


# ---------------------------------------------------------------------------------
# Run the Streamlit app
# ---------------------------------------------------------------------------------
if __name__ == "__main__":
    streamlit_app()
