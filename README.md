# SPIDER 🕷️: Scalable Product Identification and Discovery for Ecommerce Reconnaissance

SPIDER is a scalable web crawler designed to discover product URLs across various e-commerce websites. This project uses a hybrid approach combining traditional web crawling techniques with modern LLM-based link classification to handle diverse e-commerce platforms efficiently.

[Demo Link](placeholder)

## Features

- **Intelligent URL Discovery**: Uses both heuristic patterns and LLM-based classification to accurately identify product pages
- **Dynamic Content Handling**: Supports modern e-commerce sites with infinite scrolling and JavaScript-rendered content
- **Parallel Processing**: Implements async/await patterns for concurrent crawling of multiple categories
- **Hybrid Parsing Strategy**: Combines Selenium for dynamic content rendering with BeautifulSoup for efficient HTML parsing
- **Smart Link Classification**: Two-stage approach using direct heuristics first, followed by LLM validation for ambiguous cases

## Technical Architecture

### Core Components

1. **Content Fetcher** (`fetch_category_page_content`)
   - Uses headless Selenium for JavaScript-rendered content
   - Handles infinite scrolling through scroll simulation
   - Implements waiting mechanisms for dynamic content loading

2. **Link Classifier** (`determine_link_type`)
   - Analyzes URL patterns, HTML structure, and contextual clues
   - Uses multiple heuristics including:
     - Direct product URL patterns
     - Product-related class names
     - Price indicators
     - "Add to Cart" proximity

3. **LLM Validator** (`validate_links_with_llm`)
   - Processes ambiguous links in batches
   - Uses Groq API for intelligent link classification
   - Provides YES/NO verdicts for product page identification

4. **Async Crawler** (`async_crawl_category_page`)
   - Implements concurrent processing of category pages
   - Manages crawler state and visited URLs
   - Ensures efficient resource utilization

## Requirements

- Python 3.8+
- Chrome WebDriver
- Required Python packages:
  - selenium
  - beautifulsoup4
  - groq
  - asyncio

## Usage

1. Set up your Groq API credentials:
```bash
export GROQ_API_KEY='your-api-key'
```

2. Prepare your category URLs:
```python
category_urls = [
    "https://example.com/category1",
    "https://example.com/category2"
]
```

3. Run the crawler:
```bash
python main.py
```

## Output

The crawler generates a JSON file (`crawl_results.json`) containing discovered product URLs mapped to their source categories:

```json
{
    "https://example.com/category1": [
        "https://example.com/product1",
        "https://example.com/product2"
    ],
    "https://example.com/category2": [
        "https://example.com/product3",
        "https://example.com/product4"
    ]
}
```

## Design Decisions

1. **Selenium + BeautifulSoup**: 
   - Selenium handles dynamic content rendering
   - BeautifulSoup provides efficient HTML parsing
   - Combination optimizes for both accuracy and performance

2. **LLM Integration**:
   - Handles ambiguous cases where traditional patterns fail
   - Adapts to diverse e-commerce platforms without specific rules
   - Reduces maintenance of pattern databases

3. **Async Implementation**:
   - Enables parallel processing of multiple category pages
   - Improves throughput and resource utilization
   - Maintains scalability for multiple domains

## Limitations and Future Improvements

1. **Current Limitations**:
   - Fixed crawl depth (demo configuration)
   - Basic error handling
   - Limited pagination support

2. **Planned Enhancements**:
   - Configurable crawl depth per domain
   - Advanced pagination handling
   - Robust error handling with retries
   - Machine learning for dynamic heuristic updates
   - Rate limiting and politeness delays
   - Sitemap.xml integration

## Contributing

This project is currently a demonstration version. For production use, consider implementing the planned enhancements mentioned above.