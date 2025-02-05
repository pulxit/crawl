import streamlit as st
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urljoin, urlparse
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import json
import asyncio

# LLM API integration using groq
from groq import Groq

# Create a global groq client instance
groq_client = Groq()


def fetch_category_page_content(url):
    """
    Uses headless Selenium to fetch a category page with dynamic JS-rendered
    content, handling infinite scrolling until no new content is loaded.
    """
    try:
        options = Options()
        options.headless = True
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        # Extra options needed in containerized environments like Streamlit Cloud.
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        
        # Specify the path to the Chromium browser binary.
        options.binary_location = "/usr/bin/chromium-browser"
        
        # Create a Service object with the path to the ChromeDriver installed via packages.txt.
        service = Service(executable_path="/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=options)
        
        driver.get(url)
        # Initial wait for content to load
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
    
    - direct_product is True if high-confidence signals are present.
    - ambiguous is True if a product keyword exists in the href but the context is uncertain.
    - context_snippet provides a sample of nearby HTML text.
    """
    href = a_tag.get("href")
    if not href:
        return (False, False, "")
    direct_product = False
    ambiguous = False
    product_keywords = ['product', 'item']

    # Check for direct URL patterns (e.g., /product/ or /item/)
    for keyword in product_keywords:
        if re.search(rf"/{keyword}/", href):
            direct_product = True

    # Check if parent element has product-related classes
    parent = a_tag.parent
    if parent and parent.has_attr("class"):
        parent_classes = " ".join(parent["class"])
        if "product-card" in parent_classes or "product" in parent_classes or "item" in parent_classes:
            direct_product = True

    # Check the anchor text itself for price or "Add to Cart" nearby
    anchor_text = a_tag.get_text().strip()
    if re.search(r"\$\d+", anchor_text) or "add to cart" in anchor_text.lower():
        direct_product = True

    if parent:
        parent_text = parent.get_text(separator=" ", strip=True)
        if re.search(r"\$\d+", parent_text) or "add to cart" in parent_text.lower():
            direct_product = True

    # If no high-confidence signal but the URL contains product keywords, mark as ambiguous.
    if not direct_product and any(kw in href for kw in product_keywords):
        ambiguous = True

    # Use parent's text as context for LLM (truncated to 200 characters)
    context_snippet = ""
    if parent:
        context_snippet = parent.get_text(separator=" ", strip=True)[:200]
    return (direct_product, ambiguous, context_snippet)


def is_internal_url(url, base_netloc):
    """
    Checks if the URL is internal based on the base domain netloc.
    """
    try:
        parsed = urlparse(url)
        if parsed.netloc == "" or parsed.netloc == base_netloc:
            return True
        # Also handle subdomains (e.g., shop.example.com for example.com)
        if parsed.netloc.endswith(base_netloc):
            return True
    except Exception:
        pass
    return False


def validate_links_with_llm(batch):
    """
    Given a batch of ambiguous links (each a tuple of (url, context)), 
    send them to the LLM API (via groq) for product page validation.
    The prompt instructs the LLM to return YES/NO answers in order.
    
    Returns: a list of verdicts ("YES" or "NO") corresponding to the batch.
    """
    prompt_lines = [
        "Determine if these links point to product pages. Reply 'YES' or 'NO' for each:"
    ]
    for idx, (link, context) in enumerate(batch, start=1):
        # Truncate context to 200 chars (it should already be shortened)
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
    # Parse the expected response lines (e.g., "1. YES")
    for line in response.splitlines():
        line_clean = line.strip().upper()
        if "YES" in line_clean:
            verdicts.append("YES")
        elif "NO" in line_clean:
            verdicts.append("NO")
    # Make sure we have a verdict for each link; default to "NO" if missing.
    if len(verdicts) < len(batch):
        verdicts.extend(["NO"] * (len(batch) - len(verdicts)))
    return verdicts


def crawl_category_page(url):
    """
    Crawls a given category page URL to find product URLs.
    
    Begins at the category page, crawls internal links up to a shallow depth,
    applies direct heuristics to filter product links, and batches ambiguous
    links for LLM validation.
    """
    print(f"Crawling category page: {url}")
    
    # Ensure the URL string includes a scheme
    if not url.startswith("http"):
        category_url = "http://" + url
    else:
        category_url = url
    
    parsed_base = urlparse(category_url)
    base_netloc = parsed_base.netloc
    
    visited = set()
    to_visit = [(category_url, 0)]
    # No pagination, so only the initial page is processed.
    max_depth = 0
    
    product_urls = set()
    ambiguous_links = []
    
    while to_visit:
        current_url, depth = to_visit.pop(0)
        if current_url in visited or depth > max_depth:
            continue
        visited.add(current_url)
        print(f"Fetching: {current_url} (depth {depth})")
        # Use the infinite scrolling fetch to fully load category content
        content = fetch_category_page_content(current_url)
        if not content:
            continue
        
        soup = BeautifulSoup(content, "html.parser")
        a_tags = soup.find_all("a", href=True)
        for a in a_tags:
            href = a["href"]
            absolute_url = urljoin(current_url, href)
            # Only traverse internal links.
            if not is_internal_url(absolute_url, base_netloc):
                continue
            
            # Determine if link is directly a product link or ambiguous.
            direct, ambiguous, context = determine_link_type(a)
            if direct:
                product_urls.add(absolute_url)
            elif ambiguous:
                ambiguous_links.append((absolute_url, context))
            
            # Enqueue link for further crawling if not yet visited.
            if absolute_url not in visited and depth < max_depth:
                to_visit.append((absolute_url, depth + 1))
        
        # Pagination removed: do not follow "Next" links.
    
    # Process ambiguous links in batches (e.g., 10 per batch).
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
    - Enter one or more category URLs (one per line) into the text area below.
    - Category URLs should be pages that list products, such as a homepage, category page, or search results page.
    - Click the **Crawl** button to begin crawling the provided URLs.
    - The app will display the product links found on each page.
    - Use the download button to save the results as a JSON file.
    """)
    
    input_text = st.text_area("Enter category URLs (one per line)", height=150)
    
    if st.button("Crawl"):
        if input_text.strip() == "":
            st.warning("Please enter at least one URL.")
        else:
            category_urls = [line.strip() for line in input_text.splitlines() if line.strip()]
            results = {}
            progress_bar = st.progress(0)
            status_text = st.empty()
            # Crawl each URL sequentially and update the progress bar.
            for i, url in enumerate(category_urls):
                with st.spinner(f"Crawling {url} ..."):
                    product_links = crawl_category_page(url)
                    results[url] = product_links
                progress_bar.progress((i + 1) / len(category_urls))
            st.success("Crawling complete!")
            st.subheader("Crawl Results:")
            st.json(results)
            
            # Provide a download button for the JSON results.
            json_results = json.dumps(results, indent=4)
            st.download_button("Download JSON results", data=json_results, file_name="crawl_results.json", mime="application/json")


# ---------------------------------------------------------------------------------
# Run the Streamlit app
# ---------------------------------------------------------------------------------
if __name__ == "__main__":
    streamlit_app()
