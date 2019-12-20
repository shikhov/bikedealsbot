# -*- coding: utf-8 -*-

import json
import logging
import re
import sys
import urllib
import urllib2
import ast
from datetime import datetime

import webapp2
from google.appengine.ext import ndb

from config import TOKEN

APIURL = 'https://api.telegram.org/bot'

reload(sys)
sys.setdefaultencoding('utf8')

class Prod(ndb.Model):
    prodid = ndb.StringProperty()
    chatid = ndb.IntegerProperty()
    url = ndb.StringProperty()
    name = ndb.StringProperty()
    price = ndb.IntegerProperty()
    currency = ndb.StringProperty()
    lastcheck = ndb.StringProperty()
    store = ndb.StringProperty()
    errors = ndb.IntegerProperty(default=0)
    history = ndb.StringProperty(default='')

class User(ndb.Model):
    chatid = ndb.IntegerProperty()
    username = ndb.StringProperty()
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    enable = ndb.BooleanProperty()

def tgMsg(msg, chat_id, reply_to=0):
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
            fr = message.get('from')
            message_id = message['message_id']
            chat_id = message['chat']['id']
            chat_type = message['chat']['type']
            username = fr.get('username')
            first_name = fr.get('first_name')
            last_name = fr.get('last_name')
            text = message.get('text')

            price = None
            itemname = None

            if text:
                if chat_type == 'private':
                    if text == '/start':
                        tgMsg(msg=u'️Присылайте мне ссылки на товары из chainreactioncycles.com, а я буду отслеживать их цены 😉', chat_id=chat_id)
                        user = User.get_or_insert(str(chat_id))
                        user.chatid = chat_id
                        user.username = username
                        user.first_name = first_name
                        user.last_name = last_name
                        user.enable = True
                        user.put()

                    if text == '/list':
                        tgMsg(msg=getlist(chat_id), chat_id=chat_id)

                    if text.startswith('/del_'):
                        deleteprod(text)
                        tgMsg(msg=u'️Удалено\n', chat_id=chat_id)

                rg = re.search(ur'(https?://www\.chainreactioncycles\.com/\S+)', text)
                if rg:
                    product = parseCRC(rg.group(1))
                    if product:
                        itemname = product['name']
                        price = product['textprice']

                        if chat_type == 'private':
                            addprod(product, chat_id, message_id)
                    elif chat_type == 'private':
                        tgMsg(msg=u'Не смог найти цену 😧\n', chat_id=chat_id, reply_to=message_id)

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

                if price and itemname and chat_type != 'private':
                    logging.info('name: ' + itemname)
                    logging.info('price: ' + price)
                    tgMsg(msg=itemname + '\n' + price, chat_id=chat_id, reply_to=message_id)


def parseCRC(url):
    headerslist = {
        'RUB': {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=RU; languageCode=en; currencyCode=RUB'},
        'GBP': {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=GB; languageCode=en; currencyCode=GBP'}}

    url = urllib.quote(url.encode('utf-8'), ':/%')

    for currency in headerslist:
        request = urllib2.Request(url, None, headerslist[currency])
        content = urllib2.urlopen(request).read()
        matches = re.search(ur'window\.universal_variable\s+=\s+(.+?)</script>', content, re.DOTALL)
        if matches:
            universal = ast.literal_eval(matches.group(1))
            if 'product' in universal and universal['product']['price']:
                product = universal['product']
                product['currency'] = currency
                product['store'] = 'CRC'
                product['url'] = 'https://www.chainreactioncycles.com' + product['url']
                product['name'] = product['manufacturer'] + ' ' + product['name']
                textprice = str(product['price'])
                product['lowprice'] = int(re.sub('^(\d+).*', r'\1', textprice))
                textprice = re.sub('\.\d+', '', textprice)
                textprice = re.sub('-', ' - ', textprice)
                product['textprice'] = textprice + ' ' + product['currency']
                return product
    return None

class checkHandler(webapp2.RequestHandler):
    def get(self):
        msgs = {}
        prices = {}
        enabled_users = {}

        for user in User.query(User.enable == True).fetch():
            enabled_users[user.chatid] = 'foo'

        for prod in Prod.query().fetch():
            if prod.chatid in enabled_users:
                changed = False

                if prod.prodid in prices and prices[prod.prodid] < prod.price:
                    changed = True
                else:
                    prices[prod.prodid] = getprice(prod.url)
                    if prices[prod.prodid] < prod.price:
                        changed = True

                if prices[prod.prodid] == sys.maxint:
                    prod.errors += 1
                else:
                    prod.errors = 0

                if changed:
                    msg = '<a href="' + prod.url + '">' + prod.name + '</a>' + '\n<b>' + str(prices[prod.prodid]) + '</b> ' + prod.currency + u' (было: ' + str(prod.price) + ' ' + prod.currency + ')'
                    if prod.chatid in msgs:
                        msgs[prod.chatid] += '\n\n' + msg
                    else:
                        msgs[prod.chatid] = msg
                    if prod.history == '':
                        prod.history += str(prod.price) + ' (' + datetime.now().strftime('%d.%m.%Y') + ')\n'
                    prod.history += str(prices[prod.prodid]) + ' (' + datetime.now().strftime('%d.%m.%Y') + ')\n'
                    prod.price = prices[prod.prodid]

                prod.lastcheck = datetime.now().strftime('%d.%m.%Y %H:%M')
                prod.put()

        for chatid in msgs:
            try:
                tgMsg('💥 Снижение цены!\n\n' + msgs[chatid], chatid)
            except urllib2.HTTPError as e:
                if e.reason == 'Forbidden':
                    disableuser(chatid)


def getlist(chatid):
    prods = Prod.query(Prod.chatid == chatid).fetch()
    if len(prods) > 0:
        msg = 'Отслеживаемые товары:\n\n'
        for prod in prods:
            warn = '' if prod.errors == 0 else '⚠️ Ошибка (возможно, ссылка неактуальна)\n'
            msg += '<a href="' + prod.url + '">' + prod.name + '</a>\n' + warn + 'Удалить: /del_' + str(prod.key.id()) + '\n\n'
        msg += 'Последняя проверка: <i>' + prod.lastcheck + ' UTC</i>'
    else:
        msg = 'Ваш список пуст'
    return msg

def addprod(product, chat_id, message_id):
    prodid = product['id']
    url = product['url']
    price = product['lowprice']
    name = product['name']
    currency = product['currency']
    store = product['store']

    entities = Prod.query(Prod.chatid == chat_id, Prod.prodid == prodid).fetch()
    if len(entities) > 0:
        tgMsg(msg=u'️☝️ Ссылка уже есть в вашем списке\n', chat_id=chat_id, reply_to=message_id)
    else:
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        prod = Prod(prodid=prodid, chatid=chat_id, url=url, price=price, name=name, currency=currency, store=store, lastcheck=now)
        prod.put()
        tgMsg(msg=u'✔️ Добавлено к отслеживанию\n', chat_id=chat_id, reply_to=message_id)

def deleteprod(cmd):
    id = int(cmd.split('_')[1])
    ndb.Key(Prod, id).delete()

def disableuser(chatid):
    user = User.get_or_insert(str(chatid))
    user.enable = False
    user.put()

def getprice(url):
    product = parseCRC(url)
    if product:
        return product['lowprice']
    return sys.maxint


app = webapp2.WSGIApplication([
    ('/', tgHandler),
    ('/checkprices', checkHandler)
])
