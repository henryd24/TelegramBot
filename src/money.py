from bs4 import BeautifulSoup
import requests

bse_list = ['quote/USD-COP']
start_url = 'https://google.com/finance/'

def google_trm():
    """
    Retrieves the current exchange rate and stock information from Google Finance.

    Returns:
        str: A formatted string containing the conversion rate, current price, and previous closing price.
    """
    msg = ''
    for path in reversed(bse_list):
        response = requests.get(start_url+path)
        html = BeautifulSoup(response.text,'html.parser')
        stock_name = html.find(class_='zzDege').text.strip()
        current_price = html.find(class_='YMlKec fxKbKc').text.strip()
        previous_closing = html.find(class_='P6K39c').text.strip()
        txt = f"Conversion: {stock_name}\n" \
              f"Valor Actual: {current_price}\n" \
              f"Cierre Anterior: {previous_closing}\n" \
              f"-------------------\n"
        msg += txt
    return msg