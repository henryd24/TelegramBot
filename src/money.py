from .tables import get_shared_fetcher
from .logger import setup_logging

bse_list = ['quote/USD-COP']
start_url = 'https://google.com/finance/'
logger = setup_logging()

def node_text(nodes):
    if not nodes:
        return ""
    node = nodes[0]
    if isinstance(node, str):
        return node.strip()
    if hasattr(node, "text"):
        return node.text.strip()
    if hasattr(node, "extract"):
        ex = node.extract()
        if isinstance(ex, (list, tuple)):
            return str(ex[0]).strip() if ex else ""
        return str(ex).strip()
    return str(node).strip()

def google_trm() -> str:
    """
    Retrieves the current exchange rate and stock information from Google Finance.

    Returns:
        str: A formatted string containing the conversion rate, current price, and previous closing price.
    """
    msg = ''
    for path in reversed(bse_list):
        fetcher = get_shared_fetcher()
        html = fetcher.get(start_url + path)
        stock_name_nodes = html.css('.JV7gl')
        current_price_nodes = html.css('.Pdsbrc')
        previous_closing_nodes = html.css('.u77W5d')
        logger.debug({
            "stock_name_nodes": stock_name_nodes,
            "current_price_nodes": current_price_nodes,
            "previous_closing_nodes": previous_closing_nodes
        })
        stock_name = node_text(stock_name_nodes)
        current_price = node_text(current_price_nodes)
        previous_closing = node_text(previous_closing_nodes)
        
        logger.debug({
            "stock_name": stock_name,
            "current_price": current_price,
            "previous_closing": previous_closing
        })
        txt = f"Conversion: {stock_name}\n" \
              f"Valor Actual: {current_price}\n" \
              f"Cierre Anterior: {previous_closing}\n" \
              f"-------------------\n"
        msg += txt
    return msg
