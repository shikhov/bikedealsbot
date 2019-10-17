# -*- coding: utf-8 -*-

import json
import logging
import urllib
import urllib2
import webapp2
import re
import sys
import multipart

from config import TOKEN

APIURL = 'https://api.telegram.org/bot'

reload(sys)
sys.setdefaultencoding('utf8')

def tgReply(msg, chat_id, reply_to):
    urllib2.urlopen(APIURL + TOKEN + '/sendMessage', urllib.urlencode({
        'chat_id': chat_id,
        'text': msg.encode('utf-8'),
        'disable_web_page_preview': 'true',
        'parse_mode': 'HTML',
        'reply_to_message_id': reply_to,
    }))

class tgHandler(webapp2.RequestHandler):
    def post(self):
        body = json.loads(self.request.body)
        logging.info(json.dumps(body, indent=4))

        if 'message' in body:
            message = body['message']
            message_id = message['message_id']
            chat_id = message['chat']['id']
            text = message.get('text')

            price = None
            itemname = None

            if text:
                rg = re.search(ur'(https?://www\.chainreactioncycles\.com/\S+)', text)
                if rg:
                    itemurl = urllib.quote(rg.group(1).encode('utf-8'), ':/%')
                    logging.info(itemurl)
                    headers = {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=RU; languageCode=en; currencyCode=RUB'}
                    request = urllib2.Request(itemurl, None, headers)
                    content = urllib2.urlopen(request).read()
                    matches = re.search(ur'<li class="crcPDPTitle">.+?<meta itemprop="name" content="(.+?)".+?crcPDPPriceCurrent.+?<meta itemprop="priceCurrency" content="(\w+)".+?(\d+)<span class="decimal">(.+?(\d+)<span class="decimal">)?', content, re.DOTALL)
                    if matches:
                        if matches.group(5):
                            price = matches.group(3) + ' - ' + matches.group(5) + ur' р.'
                        else:
                            price = matches.group(3) + ur' р.'
                        itemname = matches.group(1)

                rg = re.search(ur'(https?://www\.wiggle\.(co\.uk|com|ru)/)(\S+)', text)
                if rg:
                    urltmp = rg.group(1) + rg.group(3)
                    itemurl = urllib.quote(urltmp.encode('utf-8'), ':/%') + '?curr=USD&dest=24'
                    opener = urllib2.build_opener()
                    content = opener.open(itemurl).read()
                    matches = re.search(ur'<h1 id="productTitle" class="bem-heading--1" itemprop="name">(.+?)</h1>.+?<span class="js-unit-price" data-default-value="(\$[\d,]+)(.+?(\$[\d,]+))?', content, re.DOTALL)
                    if matches:
                        if matches.group(2) == matches.group(4):
                            price = matches.group(2)
                        else:
                            price = matches.group(2) + " - " + matches.group(4)
                        itemname = matches.group(1)

                rg = re.search(ur'(https://www\.bike24\.com/\S+)', text)
                if rg:
                    if '?' in rg.group(1):
                        itemurl = rg.group(1) + ';country=23;action=locale_select'
                    else:
                        itemurl = rg.group(1) + '?country=23;action=locale_select'
                    opener = urllib2.build_opener()
                    content = opener.open(itemurl).read()
                    matches = re.search(ur'<h1 class="col-md-14 col-lg-14" itemprop="name">(.+?)</h1>.+?<span content="(\d+).+?" itemprop="price" class="text-value js-price-value">', content, re.DOTALL)
                    if matches:
                        itemname = matches.group(1)
                        price = matches.group(2) + ur' €'

                rg = re.search(ur'(https://www\.bike-discount\.de/\S+)', text)
                if rg:
                    itemurl = rg.group(1) + '?currency=1&delivery_country=144'
                    opener = urllib2.build_opener()
                    content = opener.open(itemurl).read()
                    matches = re.search(ur'<meta itemprop="name" content="(.+?)"><meta itemprop="price" content="(\d+)', content)
                    if matches:
                        itemname = matches.group(1)
                        price = matches.group(2) + ur' €'

                rg = re.search(ur'(https://www\.bike-components\.de/\S+)', text)
                if rg:
                    itemurl = rg.group(1)
                    logging.info(itemurl)
                    opener = urllib2.build_opener()
                    content = opener.open(itemurl).read()
                    matches = re.search(ur'data-product-name="(.+?)".+data-price="(.+?)"', content)
                    if matches:
                        itemname = matches.group(1)
                        price = matches.group(2)

                if price and itemname:
                    logging.info('name: ' + itemname)
                    logging.info('price: ' + price)
                    tgReply(msg=itemname + '\n' + price, chat_id=chat_id, reply_to=message_id)

                rg = re.search(ur'(https?://www\.gpsies\.com/.+?\?fileId=(\w+))', text)
                if rg:
                    fileid = rg.group(2)
                    dfile = urllib.urlopen('http://www.gpsies.com/download.do?fileId='+fileid).read()
                    multipart.post_multipart(APIURL + TOKEN + '/sendDocument', [('chat_id', chat_id), ('reply_to_message_id', message_id)], [('document', 'track.gpx', dfile)])


app = webapp2.WSGIApplication([
    ('/', tgHandler)
])
