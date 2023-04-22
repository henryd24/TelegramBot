from bs4 import BeautifulSoup
import requests

bse_list = ['quote/USD-COP']
start_url = 'https://google.com/finance/'

def google_trm():
    msg = ''
    for path in reversed(bse_list):
        response = requests.get(start_url+path)
        html = BeautifulSoup(response.text,'html.parser')
        stock_name = html.find(class_='zzDege').text.strip()
        current_price = html.find(class_='YMlKec fxKbKc').text.strip()
        previous_closing = html.find(class_='P6K39c').text.strip()
        txt = """Conversion: {stock_name}
Valor Actual: {current_price}
Cierre Anterior: {previous_closing}
-------------------\n""".format(stock_name=stock_name,
                                current_price=current_price,
                                previous_closing=previous_closing)
        msg = txt+msg
    return msg