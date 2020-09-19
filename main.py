# -*- coding: utf-8 -*-

import json
import logging
import re
import sys
import urllib
import urllib2
import ast
from time import time
from datetime import datetime

import webapp2
from google.appengine.ext import ndb

from config import TOKEN, ADMINTGID

APIURL = 'https://api.telegram.org/bot'
CACHEMINUTES = 60

reload(sys)
sys.setdefaultencoding('utf8')

class Prod(ndb.Model):
    prodid = ndb.StringProperty()
    chatid = ndb.IntegerProperty()
    url = ndb.StringProperty()
    name = ndb.StringProperty()
    price = ndb.IntegerProperty()
    pricecur = ndb.IntegerProperty()
    currency = ndb.StringProperty()
    lastcheck = ndb.StringProperty()
    store = ndb.StringProperty()
    errors = ndb.IntegerProperty(default=0)
    history = ndb.StringProperty(default='')

class SKU(ndb.Model):
    prodid = ndb.StringProperty()
    skuid = ndb.StringProperty()
    instock =ndb.BooleanProperty()
    chatid = ndb.IntegerProperty()
    url = ndb.StringProperty()
    name = ndb.StringProperty()
    variant = ndb.StringProperty()
    price = ndb.IntegerProperty()
    currency = ndb.StringProperty()
    lastcheck = ndb.StringProperty()
    store = ndb.StringProperty()
    errors = ndb.IntegerProperty(default=0)
    history = ndb.StringProperty(default='')

class SKUcache(ndb.Model):
    prodid = ndb.StringProperty()
    skuid = ndb.StringProperty()
    instock =ndb.BooleanProperty()
    url = ndb.StringProperty()
    name = ndb.StringProperty()
    variant = ndb.StringProperty()
    price = ndb.IntegerProperty()
    currency = ndb.StringProperty()
    lastcheck = ndb.StringProperty()
    timestamp = ndb.IntegerProperty()
    store = ndb.StringProperty()

class User(ndb.Model):
    chatid = ndb.IntegerProperty()
    username = ndb.StringProperty()
    first_name = ndb.StringProperty()
    last_name = ndb.StringProperty()
    enable = ndb.BooleanProperty()

class Offer(ndb.Model):
    url = ndb.StringProperty()
    data = ndb.StringProperty()
    active = ndb.BooleanProperty(default=False)

def tgMsg(msg, chat_id, reply_to=0):
    response = urllib2.urlopen(APIURL + TOKEN + '/sendMessage', urllib.urlencode({
        'chat_id': chat_id,
        'text': msg.encode('utf-8'),
        'disable_web_page_preview': 'true',
        'parse_mode': 'HTML',
        'reply_to_message_id': reply_to,
    })).read()
    return json.loads(response)

def tgEditMsg(chat_id, msg_id, text):
    response = urllib2.urlopen(APIURL + TOKEN + '/editMessageText', urllib.urlencode({
        'chat_id': chat_id,
        'message_id': msg_id,
        'text': text.encode('utf-8'),
        'parse_mode': 'HTML'
    })).read()
    return json.loads(response)

class tgHandler(webapp2.RequestHandler):
    def post(self):
        body = json.loads(self.request.body)
        logging.info(json.dumps(body, indent=4).decode('unicode-escape'))

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
                        tgMsg(msg=u'️Присылайте мне ссылки на товары из chainreactioncycles.com, а я буду отслеживать их цены и наличие 😉', chat_id=chat_id)
                        user = User.get_or_insert(str(chat_id))
                        user.chatid = chat_id
                        user.username = username
                        user.first_name = first_name
                        user.last_name = last_name
                        user.enable = True
                        user.put()

                    if text == '/list':
                        showList(chat_id)

                    if text.startswith('/add_'):
                        prodid = text.split('_')[1]
                        skuid = text.split('_')[2]
                        addVariant(prodid, skuid, chat_id, message_id, 'reply')

                    if text.startswith('/del_'):
                        deleteprod(text)
                        tgMsg(msg=u'️Удалено\n', chat_id=chat_id)

                rg = re.search(ur'(https?://www\.chainreactioncycles\.com/\S+/rp-(prod\d+))', text)
                if rg:
                    url = rg.group(1)
                    prodid = rg.group(2)
                    if chat_type == 'private':
                        showVariants(prodid, chat_id, message_id)
                    else:
                        product = parseCRC(url)
                        if product:
                            itemname = product['name']
                            price = product['textprice']

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
                if False:
                # if rg:
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
                product['lowprice'] = int(re.sub(r'^(\d+).*', r'\1', textprice))
                textprice = re.sub(r'\.\d+', '', textprice)
                textprice = re.sub('-', ' - ', textprice)
                product['textprice'] = textprice + ' ' + product['currency']
                return product
    return None

def getCRCvariants(prodid):
    variants = {}
    tsnow = int(time()) - CACHEMINUTES * 60
    entities = SKUcache.query(SKUcache.prodid == prodid, SKUcache.timestamp >= tsnow).fetch()
    if entities:
        for cache in entities:
            skuid = cache.skuid
            variants[skuid] = {}
            variants[skuid]['variant'] = cache.variant
            variants[skuid]['prodid'] = cache.prodid
            variants[skuid]['price'] = cache.price
            variants[skuid]['currency'] = cache.currency
            variants[skuid]['store'] = cache.store
            variants[skuid]['url'] = cache.url
            variants[skuid]['name'] = cache.name
            variants[skuid]['instock'] = cache.instock

        return variants

    return parseCRC2(prodid)


def parseCRC2(prodid):
    headerslist = {
        'RUB': {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=RU; languageCode=en; currencyCode=RUB'},
        'GBP': {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=GB; languageCode=en; currencyCode=GBP'}}

    url = 'https://www.chainreactioncycles.com/en/rp-' + prodid

    for currency in headerslist:
        request = urllib2.Request(url, None, headerslist[currency])
        try:
            content = urllib2.urlopen(request).read()
        except Exception:
            return None

        matches = re.search(ur'window\.universal_variable\s+=\s+(.+?)</script>', content, re.DOTALL)
        if matches:
            universal = ast.literal_eval(matches.group(1))
            if 'product' in universal and universal['product']['price']:
                product = universal['product']
                prodid = product['id']
                produrl = 'https://www.chainreactioncycles.com' + product['url']
                prodname = product['manufacturer'] + ' ' + product['name']
            else:
                continue

            matches = re.search(ur'var\s+variantsAray\s+=\s+(\[.+?);', content, re.DOTALL)
            if matches:
                options = ast.literal_eval(matches.group(1))
            else:
                continue

            matches = re.search(ur'var\s+allVariants\s+=\s+({.+?);', content, re.DOTALL)
            if matches:
                variants = {}
                skus = ast.literal_eval(matches.group(1))['variants']
                for sku in skus:
                    skuid = sku['skuId']
                    variants[skuid] = {}

                    varNameArray = []
                    for option in options:
                        if sku[option]: varNameArray.append(sku[option])
                    variants[skuid]['variant'] = ', '.join(varNameArray)
                    variants[skuid]['prodid'] = prodid
                    variants[skuid]['price'] = int(re.sub(r'^\D*(\d+).*', r'\1', sku['RP']))
                    variants[skuid]['currency'] = currency
                    variants[skuid]['store'] = 'CRC'
                    variants[skuid]['url'] = produrl
                    variants[skuid]['name'] = prodname
                    if sku['isInStock'] == 'true':
                        variants[skuid]['instock'] = True
                    else:
                        variants[skuid]['instock'] = False
                    variants[skuid]['cache'] = ' (NEW parse)'

                cacheVariants(variants)
                return variants
    return None



def showVariants(prodid, chat_id, message_id):
    tgresult = tgMsg(msg='🔎 Ищу информацию о товаре...', chat_id=chat_id, reply_to=message_id)
    tgmsgid = tgresult['result']['message_id']
    firstPage = True
    msg = ''
    msghdr = ''

    variants = getCRCvariants(prodid)
    if variants:
        if len(variants) == 1:
            skuid = list(variants)[0]
            addVariant(prodid, skuid, chat_id, tgmsgid, 'edit')
            return
        for skuid in sorted(variants):
            sku = variants[skuid]
            msghdr = sku['name'] + '\n\n'
            line = getSkuString(sku, ['icon']) + '\n<i>Добавить: /add_' + sku['prodid'] + '_' + skuid + '</i>\n\n'
            if len(msghdr + msg + line) > 4096:
                if firstPage:
                    tgEditMsg(text=msghdr + msg, chat_id=chat_id, msg_id=tgmsgid)
                else:
                    tgMsg(msg=msg, chat_id=chat_id)
                msg = ''
                firstPage = False
            msg += line
    else:
        msg = 'Не смог найти цену 😧'

    if msg:
        if firstPage:
            tgEditMsg(text=msghdr + msg, chat_id=chat_id, msg_id=tgmsgid)
        else:
            tgMsg(msg=msg, chat_id=chat_id)


def getSkuString(sku, options):
    if isinstance(sku, dict):
        instock = sku['instock']
        url = sku['url']
        name = sku['name']
        variant = sku['variant']
        price = str(sku['price'])
        currency = sku['currency']
    if isinstance(sku, SKU):
        instock = sku.instock
        url = sku.url
        name = sku.name
        variant = sku.variant
        price = str(sku.price)
        currency = sku.currency

    icon = ''
    urlname = ''

    if 'url' in options:
        urlname = '<a href="' + url + '">' + name + '</a>' + '\n'
    if 'icon' in options:
        icon = '✅ ' if instock else '🚫 '

    return urlname + icon + variant + ' <b>' + price + ' ' + currency + '</b>'


def checkProd():
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
                disableUser(chatid)


def checkSKU():
    def addMsg(msg):
        if dbsku.chatid in msgs:
            msgs[dbsku.chatid] += '\n\n' + msg
        else:
            msgs[dbsku.chatid] = msg

    msgs = {}
    enabled_users = {}

    for user in User.query(User.enable == True).fetch():
        enabled_users[user.chatid] = 'foo'

    for dbsku in SKU.query().fetch():
        if dbsku.chatid in enabled_users:
            variants = getCRCvariants(dbsku.prodid)
            if variants and dbsku.skuid in variants:
                sku = variants[dbsku.skuid]
                skustring = getSkuString(sku, ['url'])
                if sku['instock'] and sku['instock'] != dbsku.instock:
                    addMsg('✅ Снова в наличии!\n' + skustring)
                if not sku['instock'] and sku['instock'] != dbsku.instock:
                    addMsg('🚫 Не в наличии\n' + skustring)
                if sku['price'] < dbsku.price and sku['instock']:
                    addMsg('📉 Снижение цены!\n' + skustring + ' (было: ' + str(dbsku.price) + ' ' + dbsku.currency + ')')
                if sku['price'] > dbsku.price and sku['instock']:
                    addMsg('📈 Повышение цены\n' + skustring + ' (было: ' + str(dbsku.price) + ' ' + dbsku.currency + ')')

                dbsku.instock = sku['instock']
                dbsku.price = sku['price']
                dbsku.errors = 0
            else:
                dbsku.errors += 1

            dbsku.lastcheck = datetime.now().strftime('%d.%m.%Y %H:%M')
            dbsku.put()

    for chatid in msgs:
        try:
            tgMsg(msgs[chatid], chatid)
        except urllib2.HTTPError as e:
            if e.reason == 'Forbidden':
                disableUser(chatid)


class checkHandler(webapp2.RequestHandler):
    def get(self):
        checkProd()
        checkSKU()


class checkOffersHandler(webapp2.RequestHandler):
    def get(self):
        url = 'https://www.bike-components.de/en/'
        offer = Offer.get_or_insert(url)
        opener = urllib2.build_opener()
        content = opener.open(url).read()
        matches = re.search(ur'([^>]*free shipping[^<]*)', content, re.IGNORECASE)
        if matches:
            data = matches.group(1)
            if not offer.active:
                offer.data = data
                offer.active = True
                tgMsg(msg=data + '\n' + url, chat_id=ADMINTGID)
        else:
            if offer.active:
                tgMsg(msg='ENDED: ' + offer.data + '\n' + url, chat_id=ADMINTGID)
            offer.active = False

        offer.put()

class clearCacheHandler(webapp2.RequestHandler):
    def get(self):
        clearCacheVariants()

def showList(chatid):
    msg = 'Отслеживаемые товары:\n\n'

    prods = Prod.query(Prod.chatid == chatid).fetch()
    if prods:
        for prod in prods:
            warn = '' if prod.errors == 0 else '⚠️ Ошибка (возможно, ссылка неактуальна)\n'
            line = '<a href="' + prod.url + '">' + prod.name + '</a>\n' + warn + 'Удалить: /del_p_' + str(prod.key.id()) + '\n\n'
            if len(msg + line) > 4096:
                tgMsg(msg=msg, chat_id=chatid)
                msg = ''
            msg += line

    skus = SKU.query(SKU.chatid == chatid).order(SKU.prodid, SKU.skuid).fetch()
    if skus:
        for sku in skus:
            warn = '' if sku.errors == 0 else '⚠️ Ошибка (возможно, ссылка неактуальна)\n'
            line = getSkuString(sku, ['url','icon']) + '\n' + warn + 'Удалить: /del_s_' + str(sku.key.id()) + '\n\n'
            if len(msg + line) > 4096:
                tgMsg(msg=msg, chat_id=chatid)
                msg = ''
            msg += line

    if not prods and not skus:
        tgMsg(msg='Ваш список пуст', chat_id=chatid)
        return

    if msg:
        tgMsg(msg=msg, chat_id=chatid)


def addprod(product, chat_id, message_id):
    prodid = product['id']
    url = product['url']
    price = product['lowprice']
    name = product['name']
    currency = product['currency']
    store = product['store']

    entities = Prod.query(Prod.chatid == chat_id, Prod.prodid == prodid).fetch()
    if entities:
        tgMsg(msg=u'️☝️ Ссылка уже есть в вашем списке\n', chat_id=chat_id, reply_to=message_id)
    else:
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        prod = Prod(prodid=prodid, chatid=chat_id, url=url, price=price, name=name, currency=currency, store=store, lastcheck=now)
        prod.put()
        tgMsg(msg=u'✔️ Добавлено к отслеживанию', chat_id=chat_id, reply_to=message_id)

def addVariant(prodid, skuid, chat_id, message_id, msgtype):
    entities = SKU.query(SKU.chatid == chat_id, SKU.prodid == prodid, SKU.skuid == skuid).fetch()
    if entities:
        if msgtype == 'reply':
            tgMsg(msg='️☝️ Товар уже есть в вашем списке', chat_id=chat_id, reply_to=message_id)
        if msgtype == 'edit':
            tgEditMsg(text='️☝️ Товар уже есть в вашем списке', chat_id=chat_id, msg_id=message_id)
        return
    variants = getCRCvariants(prodid)
    if skuid not in variants:
        if msgtype == 'reply':
            tgMsg(msg='Какая-то ошибка 😧', chat_id=chat_id, reply_to=message_id)
        if msgtype == 'edit':
            tgEditMsg(text='️Какая-то ошибка 😧', chat_id=chat_id, msg_id=message_id)
        return
    sku = variants[skuid]
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    dbsku = SKU()
    dbsku.chatid = chat_id
    dbsku.skuid = skuid
    dbsku.prodid = sku['prodid']
    dbsku.variant = sku['variant']
    dbsku.url = sku['url']
    dbsku.name = sku['name']
    dbsku.price = sku['price']
    dbsku.currency = sku['currency']
    dbsku.store = sku['store']
    dbsku.instock = sku['instock']
    dbsku.lastcheck = now
    dbsku.put()

    if msgtype == 'reply':
        tgMsg(msg=dbsku.variant + '\n✔️ Добавлено к отслеживанию', chat_id=chat_id, reply_to=message_id)
    if msgtype == 'edit':
        tgEditMsg(text=dbsku.variant + '\n✔️ Добавлено к отслеживанию', chat_id=chat_id, msg_id=message_id)

def cacheVariants(variants):
    now = int(time())
    for skuid in variants:
        sku = variants[skuid]
        dbsku = SKUcache.get_or_insert(sku['prodid'] + skuid)
        dbsku.skuid = skuid
        dbsku.prodid = sku['prodid']
        dbsku.variant = sku['variant']
        dbsku.url = sku['url']
        dbsku.name = sku['name']
        dbsku.price = sku['price']
        dbsku.currency = sku['currency']
        dbsku.store = sku['store']
        dbsku.instock = sku['instock']
        dbsku.timestamp = now
        dbsku.put()

def clearCacheVariants():
    tsnow = int(time()) - CACHEMINUTES * 60
    entities = SKUcache.query(SKUcache.timestamp < tsnow).fetch()
    for cache in entities:
        cache.key.delete()

def deleteprod(cmd):
    dbtype = cmd.split('_')[1]
    dbid = int(cmd.split('_')[2])
    if dbtype == 'p':
        ndb.Key(Prod, dbid).delete()
    if dbtype == 's':
        ndb.Key(SKU, dbid).delete()

def disableUser(chatid):
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
    ('/checkprices', checkHandler),
    ('/checkoffers', checkOffersHandler),
    ('/clearcache', clearCacheHandler)
])
