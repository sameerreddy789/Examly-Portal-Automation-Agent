from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from loguru import logger

async def extract_page_data_crawlee(url: str, selector: str = "body") -> str:
    """
    Uses Crawlee to efficiently extract text data from a webpage without
    relying on expensive LLM tokens for visual grounding.
    """
    extracted_text = ""
    
    crawler = PlaywrightCrawler(
        max_requests_per_crawl=1,
        headless=True,
    )

    @crawler.router.default_handler
    async def request_handler(context: PlaywrightCrawlingContext) -> None:
        nonlocal extracted_text
        logger.info(f"🕸️ [CRAWLEE] Processing {context.request.url}")
        
        # Wait for the target element
        await context.page.wait_for_selector(selector, timeout=5000)
        
        # Extract text content
        elements = await context.page.query_selector_all(selector)
        texts = []
        for el in elements:
            text = await el.inner_text()
            if text:
                texts.append(text.strip())
                
        extracted_text = "\n".join(texts)
        logger.info(f"🕸️ [CRAWLEE] Extracted {len(extracted_text)} characters.")

    try:
        await crawler.run([url])
        return extracted_text
    except Exception as e:
        logger.error(f"❌ [CRAWLEE] Error during extraction: {e}")
        return f"Error extracting data: {e}"
