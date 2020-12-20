# -*- coding: utf-8 -*-

import json
import logging
import re
import sys
import urllib
import urllib2
import ast
import xmltodict
from time import sleep, time
from datetime import datetime

import webapp2
from google.appengine.ext import ndb

from config import TOKEN, ADMINTGID

APIURL = 'https://api.telegram.org/bot'
CACHEMINUTES = 60
ERRORMINTHRESHOLD = 10
ERRORMAXTHRESHOLD = 300

reload(sys)
sys.setdefaultencoding('utf8')


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
    info = ndb.StringProperty()

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
                        processCmdStart(chat_id=chat_id, username=username, first_name=first_name, last_name=last_name)

                    if text == '/list':
                        processCmdList(chat_id=chat_id)

                    if text.startswith('/add_'):
                        processCmdAdd(cmd=text, chat_id=chat_id, message_id=message_id)

                    if text.startswith('/del_'):
                        processCmdDel(cmd=text, chat_id=chat_id, message_id=message_id)

                    if text.startswith('/bc'):
                        processCmdBroadcast(cmd=text, chat_id=chat_id)

                    if text == '/stat':
                        processCmdStat(chat_id=chat_id)

                rg = re.search(ur'(https?://www\.chainreactioncycles\.com/\S+/rp-(prod\d+))', text)
                if rg:
                    url = 'https://www.chainreactioncycles.com/en/rp-' + rg.group(2)
                    prodid = rg.group(2)
                    if chat_type == 'private':
                        showVariants(store='CRC', url=url, prodid=prodid, chat_id=chat_id, message_id=message_id)
                    else:
                        product = parseCRC2(url)
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

                rg = re.search(ur'(https://www\.bike24\.com/p2(\d+)\.html)', text)
                if rg:
                    url = rg.group(1)
                    prodid = rg.group(2)
                    if chat_type == 'private':
                        showVariants(store='B24', url=url, prodid=prodid, chat_id=chat_id, message_id=message_id)
                    else:
                        if '?' in rg.group(1):
                            itemurl = rg.group(1) + ';country=23;action=locale_select'
                        else:
                            itemurl = rg.group(1) + '?country=23;action=locale_select'
                        try:
                            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'}
                            request = urllib2.Request(url=itemurl, headers=headers)
                            content = urllib2.urlopen(request).read()
                            matches = re.search(ur'<h1 class="col-md-14 col-lg-14" itemprop="name">(.+?)</h1>.+?<span content="(\d+).+?" itemprop="price" class="text-value js-price-value">', content, re.DOTALL)
                            if matches:
                                itemname = matches.group(1)
                                price = matches.group(2) + ur' €'
                        except urllib2.HTTPError:
                            pass

                rg = re.search(ur'(https://www\.bike-discount\.de/\S+)', text)
                if rg:
                    itemurl = rg.group(1) + '?currency=1&delivery_country=144'
                    opener = urllib2.build_opener()
                    content = opener.open(itemurl).read()
                    matches = re.search(ur'<meta itemprop="name" content="(.+?)"><meta itemprop="price" content="(\d+)', content)
                    if matches:
                        itemname = matches.group(1)
                        price = matches.group(2) + ur' €'

                rg = re.search(ur'(https://www\.bike-components\.de/\S+p(\d+)\/)', text)
                if rg:
                    url = rg.group(1)
                    prodid = rg.group(2)
                    if chat_type == 'private':
                        showVariants(store='BC', url=url, prodid=prodid, chat_id=chat_id, message_id=message_id)
                    else:
                        opener = urllib2.build_opener()
                        content = opener.open(url).read()
                        matches = re.search(ur'data-product-name="(.+?)".+data-price="(.+?)"', content)
                        if matches:
                            itemname = matches.group(1)
                            price = matches.group(2)

                if price and itemname and chat_type != 'private':
                    logging.info('name: ' + itemname)
                    logging.info('price: ' + price)
                    tgMsg(msg=itemname + '\n' + price, chat_id=chat_id, reply_to=message_id)


def processCmdStart(chat_id, username, first_name, last_name):
    msg = '️Присылайте мне ссылки на товары из веломагазинов, а я буду отслеживать их цены и наличие 😉 Поддерживаются:\nchainreactioncycles.com\nbike-components.de\nbike24.com'
    tgMsg(msg=msg, chat_id=chat_id)
    user = User.get_or_insert(str(chat_id))
    user.chatid = chat_id
    user.username = username
    user.first_name = first_name
    user.last_name = last_name
    user.enable = True
    user.put()


def processCmdList(chat_id):
    skus = SKU.query(SKU.chatid == chat_id).order(SKU.prodid, SKU.skuid).fetch()
    if not skus:
        tgMsg(msg='Ваш список пуст', chat_id=chat_id)
        return

    msg = 'Отслеживаемые товары:\n\n'

    for sku in skus:
        warn = '' if sku.errors <= ERRORMINTHRESHOLD else '⚠️ Ошибка (возможно, ссылка неактуальна)\n'
        line = getSkuString(sku, ['store', 'url','icon']) + '\n' + warn + '<i>Удалить: /del_' + str(sku.key.id()) + '</i>\n\n'
        if len(msg + line) > 4096:
            tgMsg(msg=msg, chat_id=chat_id)
            msg = ''
        msg += line

    if msg:
        tgMsg(msg=msg, chat_id=chat_id)


def processCmdAdd(cmd, chat_id, message_id):
    params = cmd.split('_')
    if len(params) == 4:
        store = params[1].upper()
        prodid = params[2]
        skuid = params[3]
        addVariant(store, prodid, skuid, chat_id, message_id, 'reply')
    else:
        tgMsg(msg='Непонятная команда 😧', chat_id=chat_id, reply_to=message_id)


def processCmdDel(cmd, chat_id, message_id):
    params = cmd.split('_')
    if len(params) == 2:
        dbid = int(params[1])
        deleteSku(dbid=dbid)
        tgMsg(msg='️Удалено', chat_id=chat_id)
    else:
        tgMsg(msg='Непонятная команда 😧', chat_id=chat_id, reply_to=message_id)


def getVariants(store, url, prodid):
    variants = {}
    tsnow = int(time()) - CACHEMINUTES * 60
    entities = SKUcache.query(SKUcache.store == store, SKUcache.prodid == prodid, SKUcache.timestamp >= tsnow).fetch()
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

    parseFunctions = {'CRC': parseCRC, 'BC': parseBC, 'B24': parseB24}
    return parseFunctions[store](url)


def parseCRC(url):
    headerslist = {
        'RUB': {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=RU; languageCode=en; currencyCode=RUB'},
        'GBP': {'User-Agent': 'Mozilla/5.0', 'Cookie': 'countryCode=GB; languageCode=en; currencyCode=GBP'}}

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
                    variants[skuid]['instock'] = sku['isInStock'] == 'true'

                cacheVariants(variants)
                return variants
    return None


def parseCRC2(url):
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


def parseBC(url):
    request = urllib2.Request(url)
    try:
        content = urllib2.urlopen(request).read()
    except Exception:
        return None

    matches = re.search(r'({ \"@context\": \"https:\\/\\/schema\.org\", \"@type\": \"Product\".+?})</script>', content, re.DOTALL)
    if not matches: return None

    variants = {}
    json = ast.literal_eval(matches.group(1))
    skus = json['offers']
    for sku in skus:
        skuid = sku['sku'].replace(str(json['sku']), '').replace('-', '')
        variants[skuid] = {}
        variants[skuid]['variant'] = sku['name'].replace('\/', '/').decode('unicode-escape')
        variants[skuid]['prodid'] = str(json['sku'])
        variants[skuid]['price'] = int(sku['priceSpecification']['price'])
        if 'True' in sku['priceSpecification']['valueAddedTaxIncluded']:
            variants[skuid]['price'] = int(sku['priceSpecification']['price']*0.84)
        variants[skuid]['currency'] = sku['priceSpecification']['priceCurrency']
        variants[skuid]['store'] = 'BC'
        variants[skuid]['url'] = url
        variants[skuid]['name'] = (json['brand']['name'] + ' ' + json['name'].replace('\/', '/')).decode('unicode-escape')
        variants[skuid]['instock'] = 'InStock' in sku['availability']

    cacheVariants(variants)
    return variants


def parseB24(url):
    request = urllib2.Request(url, None, {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'})
    try:
        content = urllib2.urlopen(request).read()
    except Exception:
        return None

    matches = re.search(r'dataLayer =\s+\[(.+?)\];', content, re.DOTALL)
    if not matches: return None

    jsdata = json.loads(matches.group(1).decode('unicode-escape'))
    if 'productPrice' not in jsdata: return None
    price = int(jsdata['productPrice'])
    prodid = str(jsdata['productId'])
    name = jsdata['productName'].replace('\/', '/')
    variant = jsdata['productVariant'].replace('\/', '/')
    currency = jsdata['currencyCode']

    namesplit = name.split(' - ')
    if len(namesplit) > 1:
        name = namesplit[0]
        variant = ', '.join(namesplit[1:]) + (', ' + variant if variant else '')

    variants = {}

    matches = re.search(r'(<select class="form-control js-product-option-select".+?</select>)', content, re.DOTALL)
    if matches:
        xml = matches.group(1).decode('unicode-escape')
        xml = xml.replace('&euro;', '')
        try:
            xmldata = xmltodict.parse(xml)
        except Exception:
            return None
        skus = xmldata['select']['option']
        if not isinstance(skus, list): skus = [skus]

        for sku in skus:
            if int(sku['@value']) < 0: continue
            skuid = sku['@value']
            variants[skuid] = {}
            vartext = re.sub(r' - add.+', '', sku['#text'])
            vartext = vartext.replace('not deliverable: ', '')
            variants[skuid]['variant'] = ((variant + ', ' if variant else '') + vartext).replace('\/', '/').strip()
            variants[skuid]['prodid'] = prodid
            if '@data-surcharge' in sku: price = int(price + float(sku['@data-surcharge']))
            variants[skuid]['price'] = price
            variants[skuid]['currency'] = currency
            variants[skuid]['store'] = 'B24'
            variants[skuid]['url'] = url
            variants[skuid]['name'] = name
            variants[skuid]['instock'] = sku['@data-stock-current'] != '0'
    else:
        variants['0'] = {}
        variants['0']['variant'] = variant
        variants['0']['prodid'] = prodid
        variants['0']['price'] = price
        variants['0']['currency'] = currency
        variants['0']['store'] = 'B24'
        variants['0']['url'] = url
        variants['0']['name'] = name
        variants['0']['instock'] = jsdata['isAvailable']

    cacheVariants(variants)
    return variants


def showVariants(store, url, prodid, chat_id, message_id):
    tgresult = tgMsg(msg='🔎 Ищу информацию о товаре...', chat_id=chat_id, reply_to=message_id)
    tgmsgid = tgresult['result']['message_id']
    firstPage = True
    msg = ''
    msghdr = ''

    variants = getVariants(store, url, prodid)
    if variants:
        if len(variants) == 1:
            skuid = list(variants)[0]
            addVariant(store, prodid, skuid, chat_id, tgmsgid, 'edit')
            return
        for skuid in sorted(variants):
            sku = variants[skuid]
            msghdr = sku['name'] + '\n\n'
            line = getSkuString(sku, ['icon']) + '\n<i>Добавить: /add_' + store.lower() + '_' +  sku['prodid'] + '_' + skuid + '</i>\n\n'
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
        store = sku['store']
    else:
        instock = sku.instock
        url = sku.url
        name = sku.name
        variant = sku.variant
        price = str(sku.price)
        currency = sku.currency
        store = sku.store

    storename = ''
    urlname = ''
    icon = ''

    if 'url' in options:
        urlname = '<a href="' + url + '">' + name + '</a>' + '\n'
    if 'icon' in options:
        icon = '✅ ' if instock else '🚫 '
    if 'store' in options:
        storename = '<code>[' + store + ']</code> '

    return storename + urlname + icon + variant + ' <b>' + price + ' ' + currency + '</b>'


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
            variants = getVariants(dbsku.store, dbsku.url, dbsku.prodid)
            if variants and dbsku.skuid in variants:
                sku = variants[dbsku.skuid]
                skustring = getSkuString(sku, ['store', 'url'])
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
        sleep(0.1)


def processCmdBroadcast(cmd, chat_id):
    if chat_id != ADMINTGID: return

    tgMsg(msg="Начало рассылки", chat_id=chat_id)
    msg = cmd[3-len(cmd):]
    for user in User.query(User.enable == True).fetch():
        try:
            tgMsg(msg=msg, chat_id=user.chatid)
            user.info = 'Sent ' + datetime.now().strftime('%d.%m.%Y %H:%M')
            user.put()
        except urllib2.HTTPError as e:
            if e.reason == 'Forbidden':
                disableUser(user.chatid)
        sleep(0.1)
    tgMsg(msg="Окончание рассылки", chat_id=chat_id)


def processCmdStat(chat_id):
    if chat_id != ADMINTGID: return

    users = str(len(User.query(User.enable == True).fetch()))
    userswsku = str(len(ndb.gql('SELECT DISTINCT chatid from SKU').fetch()))
    sku = str(len(SKU.query().fetch()))
    crc = str(len(SKU.query(SKU.store == 'CRC').fetch()))
    bc = str(len(SKU.query(SKU.store == 'BC').fetch()))
    b24 = str(len(SKU.query(SKU.store == 'B24').fetch()))

    msg = ''
    msg += '<b>Users:</b> ' + users + '\n'
    msg += '<b>Users with SKU:</b> ' + userswsku + '\n'
    msg += '<b>SKU:</b> ' + sku + '\n'
    msg += '<b>CRC:</b> ' + crc + '\n'
    msg += '<b>BC:</b> ' + bc + '\n'
    msg += '<b>B24:</b> ' + b24 + '\n'
    tgMsg(msg=msg, chat_id=chat_id)


class checkSKUHandler(webapp2.RequestHandler):
    def get(self):
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


def getURL(store, prodid):
    entities = SKUcache.query(SKUcache.store == store, SKUcache.prodid == prodid).fetch()
    if entities:
        return entities[0].url
    return None


def addVariant(store, prodid, skuid, chat_id, message_id, msgtype):
    entities = SKU.query(SKU.store == store, SKU.chatid == chat_id, SKU.prodid == prodid, SKU.skuid == skuid).fetch()
    if entities:
        if msgtype == 'reply':
            tgMsg(msg='️☝️ Товар уже есть в вашем списке', chat_id=chat_id, reply_to=message_id)
        if msgtype == 'edit':
            tgEditMsg(text='️☝️ Товар уже есть в вашем списке', chat_id=chat_id, msg_id=message_id)
        return

    url = getURL(store, prodid)
    if not url:
        if msgtype == 'reply':
            tgMsg(msg='Какая-то ошибка 😧', chat_id=chat_id, reply_to=message_id)
        if msgtype == 'edit':
            tgEditMsg(text='️Какая-то ошибка 😧', chat_id=chat_id, msg_id=message_id)
        return

    variants = getVariants(store, url, prodid)
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


def deleteSku(dbid):
    ndb.Key(SKU, dbid).delete()


def disableUser(chatid):
    user = User.get_or_insert(str(chatid))
    user.enable = False
    user.put()


app = webapp2.WSGIApplication([
    ('/', tgHandler),
    ('/checkprices', checkSKUHandler),
    ('/checkoffers', checkOffersHandler),
    ('/clearcache', clearCacheHandler)
])
