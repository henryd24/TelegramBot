import scrapy

bse_list = ['quote/USD-COP', 'quote/EUR-COP', 'quote/AMARAJABAT:NSE']


class CrlSpider(scrapy.Spider):
    name = 'crl'
   
    start_urls = ['https://google.com/finance/']


    def parse(self, response):
        for stock in bse_list:
            url_new = response.urljoin(stock)
            yield scrapy.Request(url_new, callback=self.parse_book)


    def parse_book(self, response):
        stock_name = response.xpath('//*[@class="zzDege"]/text()').extract_first()
        current_price = response.xpath('//*[@class="YMlKec fxKbKc"]/text()').extract_first()
        previous_closing = response.xpath('//*[@class="P6K39c"]/text()').extract_first()
        #stock_info = response.xpath('//*[@class="P6K39c"]/text()').extract()

        #last_closing_price = stock_info[0]
        # day_range = stock_info[1]
        # year_range = stock_info[2]
        # market_cap = stock_info[3]
        # p_e_ratio = stock_inf[4]

        yield {
            "stock_name": stock_name,
            "current_price": current_price,
            "previous_closing": previous_closing,
            #"last_closing_price": last_closing_price,
            # "day_range": day_range,
            # "year_range": year_range,
            # "market_cap": market_cap,
            # "p_e_ratio": p_e_ratio
        }