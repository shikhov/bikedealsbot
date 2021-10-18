# -*- coding: utf-8 -*-

import json
import logging
import re
import sys
import urllib
import urllib2
import ast
import xmltodict
from bs4 import BeautifulSoup
from time import sleep, time
from datetime import datetime

import webapp2
from google.appengine.ext import ndb
from google.appengine.api import urlfetch

reload(sys)
sys.setdefaultencoding('utf8')
urlfetch.set_default_fetch_deadline(60)

class Settings(ndb.Model):
    value = ndb.StringProperty()

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
    lastgoodts = ndb.IntegerProperty()
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


def getSettings(name):
    entity = Settings.get_by_id(name)
    if not entity: raise ValueError('Setting ' + name + ' doesn\'t exist!')
    return entity.value


APIURL = 'https://api.telegram.org/bot'
TOKEN = getSettings('TOKEN')
ADMINCHATID = int(getSettings('ADMINCHATID'))
BESTDEALSCHATID = int(getSettings('BESTDEALSCHATID'))
BESTDEALSMINPERCENTAGE = int(getSettings('BESTDEALSMINPERCENTAGE'))
BESTDEALSWARNPERCENTAGE = int(getSettings('BESTDEALSWARNPERCENTAGE'))
CACHELIFETIME = int(getSettings('CACHELIFETIME'))
ERRORMINTHRESHOLD = int(getSettings('ERRORMINTHRESHOLD'))
ERRORMAXDAYS = int(getSettings('ERRORMAXDAYS'))
MAXITEMSPERUSER = int(getSettings('MAXITEMSPERUSER'))


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

        if 'message' not in body: return
        message = body['message']
        text = message.get('text')
        if not text: return

        message_id = message['message_id']
        chat_id = message['chat']['id']
        chat_type = message['chat']['type']

        if chat_type != 'private':
            logging.info(json.dumps(body, indent=4).decode('unicode-escape'))
            return

        logging.debug(json.dumps(body, indent=4).decode('unicode-escape'))

        if text.startswith('/'):
            processCmd(message)
            return

        rg = re.search(ur'(https?://www\.chainreactioncycles\.com/\S+/rp-prod(\d+))', text)
        if rg:
            url = 'https://www.chainreactioncycles.com/en/rp-prod' + rg.group(2)
            showVariants(store='CRC', url=url, chat_id=chat_id, message_id=message_id)
            return

        rg = re.search(ur'(https://www\.bike24\.com/p2(\d+)\.html)', text)
        if rg:
            url = rg.group(1)
            showVariants(store='B24', url=url, chat_id=chat_id, message_id=message_id)
            return

        rg = re.search(r'(https://www\.bike-discount\.de)/.+?/.+?/([^?&]+)', text)
        if rg:
            url = rg.group(1) + '/en/buy/' + rg.group(2)
            showVariants(store='BD', url=url, chat_id=chat_id, message_id=message_id)
            return

        rg = re.search(ur'(https://www\.bike-components\.de/\S+p(\d+)\/)', text)
        if rg:
            url = rg.group(1)
            showVariants(store='BC', url=url, chat_id=chat_id, message_id=message_id)
            return


def processCmdStart(chat_id, username, first_name, last_name):
    msg = '️Присылайте мне ссылки на товары из веломагазинов, а я буду отслеживать их цены и наличие 😉 '
    msg += 'Поддерживаются:\nchainreactioncycles.com\nbike-components.de\nbike24.com\nbike-discount.de'
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

    text_array = ['Отслеживаемые товары:']

    for sku in skus:
        warn = '' if sku.errors <= ERRORMINTHRESHOLD else '⚠️ Ошибка (возможно, ссылка неактуальна)\n'
        line = getSkuString(sku, ['store', 'url', 'icon', 'price']) + '\n' + warn + '<i>Удалить: /del_' + str(sku.key.id()) + '</i>'
        text_array.append(line)

    paginatedTgMsg(text_array, chat_id)


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
        ndb.Key(SKU, dbid).delete()
        tgMsg(msg='️Удалено', chat_id=chat_id)
    else:
        tgMsg(msg='Непонятная команда 😧', chat_id=chat_id, reply_to=message_id)


def getVariants(store, url):
    variants = {}
    tsnow = int(time()) - CACHELIFETIME * 60
    entities = SKUcache.query(SKUcache.store == store, SKUcache.url == url, SKUcache.timestamp >= tsnow).fetch()
    if entities:
        for cache in entities:
            variants[cache.skuid] = {}
            variants[cache.skuid]['variant'] = cache.variant
            variants[cache.skuid]['prodid'] = cache.prodid
            variants[cache.skuid]['price'] = cache.price
            variants[cache.skuid]['currency'] = cache.currency
            variants[cache.skuid]['store'] = cache.store
            variants[cache.skuid]['url'] = cache.url
            variants[cache.skuid]['name'] = cache.name
            variants[cache.skuid]['instock'] = cache.instock
        return variants

    return globals()['parse' + store](url)


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
        if not matches: continue

        universal = ast.literal_eval(matches.group(1))
        if not ('product' in universal and universal['product']['price']): continue

        product = universal['product']
        prodid = product['id'].replace('prod', '')
        produrl = 'https://www.chainreactioncycles.com' + product['url']
        prodname = product['manufacturer'] + ' ' + product['name']

        matches = re.search(ur'var\s+variantsAray\s+=\s+(\[.+?);', content, re.DOTALL)
        if not matches: continue

        options = ast.literal_eval(matches.group(1))

        matches = re.search(ur'var\s+allVariants\s+=\s+({.+?);', content, re.DOTALL)
        if not matches: continue

        variants = {}
        skus = ast.literal_eval(matches.group(1))['variants']
        for sku in skus:
            skuid = sku['skuId'].replace('sku', '')
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


def parseBD(url):
    matches = re.search(r'(\d+)$', url)
    if not matches: return None
    prodid = matches.group(1)

    request = urllib2.Request(url + '?currency=1&delivery_country=144')
    try:
        content = urllib2.urlopen(request).read()
    except Exception:
        return None

    def findName(tag):
        return tag.name == 'meta' and tag.get('itemprop') == 'name' and tag.parent.get('itemtype') == 'http://schema.org/Product'

    def findVariants(tag):
        return tag.name == 'div' and tag.has_attr('class') and 'variantselector' in tag['class']

    def findOffers(tag):
        return tag.name == 'div' and tag.get('itemtype') == 'http://schema.org/Offer'

    soup = BeautifulSoup(content, 'lxml')
    res = soup.find_all(findName)
    if not res: return None
    if not res[0].get('content'): return None
    name = res[0]['content']

    res = soup.find_all(findVariants)
    if not res: return None
    varnames = {}

    if res[0].div:
        div_w_variants = res[0].div
        if res[0].div.div:
            div_w_variants = res[0].div.div
        for y in div_w_variants:
            if y.has_attr('data-id') and y.has_attr('data-vartext'):
                varid = y['data-id']
                vartext = y['data-vartext']
                varnames[varid] = vartext

    res = soup.find_all(findOffers)
    if not res: return None

    variants = {}
    skuid = '0'
    variant = ''

    for x in res:
        if varnames:
            if not x.parent.parent.get('id'): return None
            matches = re.search(r'(\d+)$', x.parent.parent['id'])
            if matches:
                skuid = matches.group(1)
                variant = varnames[skuid]

        instock = None
        price = None

        for child in x.children:
            if child.get('itemprop') == 'price':
                price = child['content']
            if child.get('itemprop') == 'availability':
                instock = child['content'] == 'http://schema.org/InStock'

        if instock is None or price is None: return None

        variants[skuid] = {}
        variants[skuid]['variant'] = variant
        variants[skuid]['prodid'] = prodid
        variants[skuid]['currency'] = 'EUR'
        variants[skuid]['store'] = 'BD'
        variants[skuid]['url'] = url
        variants[skuid]['name'] = name
        variants[skuid]['price'] = int(float(price))
        variants[skuid]['instock'] = instock

    cacheVariants(variants)
    return variants


def showVariants(store, url, chat_id, message_id):
    tgresult = tgMsg(msg='🔎 Ищу информацию о товаре...', chat_id=chat_id, reply_to=message_id)
    tgmsgid = tgresult['result']['message_id']
    text_array = []

    variants = getVariants(store, url)
    if variants:
        first_skuid = list(variants)[0]
        if len(variants) == 1:
            prodid = variants[first_skuid]['prodid']
            addVariant(store, prodid, first_skuid, chat_id, tgmsgid, 'edit')
            return

        text_array.append(variants[first_skuid]['name'])
        for skuid in sorted(variants):
            sku = variants[skuid]
            line = getSkuString(sku, ['icon', 'price']) + '\n<i>Добавить: /add_' + store.lower() + '_' +  sku['prodid'] + '_' + skuid + '</i>'
            text_array.append(line)
    else:
        text_array.append('Не смог найти цену 😧')

    paginatedTgMsg(text_array, chat_id, tgmsgid)



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
    pricetxt = ''

    if 'url' in options:
        urlname = '<a href="' + url + '">' + name + '</a>' + '\n'
    if 'icon' in options:
        icon = '✅ ' if instock else '🚫 '
    if 'store' in options:
        storename = '<code>[' + store + ']</code> '
    if 'price' in options:
        pricetxt = ' <b>' + price + ' ' + currency + '</b>'

    return storename + urlname + icon + variant + pricetxt


def checkSKU():
    def addMsg(msg):
        if dbsku.chatid in msgs:
            msgs[dbsku.chatid].append(msg)
        else:
            msgs[dbsku.chatid] = [msg]

    msgs = {}
    bestdeals = {}
    enabled_users = {}
    stores = {}
    now = int(time())

    for user in User.query(User.enable == True).fetch():
        enabled_users[user.chatid] = 'foo'

    for dbsku in SKU.query().fetch():
        if dbsku.chatid not in enabled_users: continue
        variants = getVariants(dbsku.store, dbsku.url)
        if variants and dbsku.skuid in variants:
            sku = variants[dbsku.skuid]
            skustring = getSkuString(sku, ['store', 'url', 'price'])
            if sku['instock'] and sku['instock'] != dbsku.instock:
                addMsg('✅ Снова в наличии!\n' + skustring)
            if not sku['instock'] and sku['instock'] != dbsku.instock:
                addMsg('🚫 Не в наличии\n' + skustring)
            if sku['price'] < dbsku.price and sku['instock']:
                addMsg('📉 Снижение цены!\n' + skustring + ' (было: ' + str(dbsku.price) + ' ' + dbsku.currency + ')')
                if dbsku.price != 0:
                    percents = int((1 - sku['price']/float(dbsku.price))*100)
                    if percents >= BESTDEALSMINPERCENTAGE:
                        bdkey = dbsku.store + dbsku.prodid + dbsku.skuid
                        bestdeals[bdkey] = skustring + ' (было: ' + str(dbsku.price) + ' ' + dbsku.currency + ') ' + str(percents) + '%'
                        if percents >= BESTDEALSWARNPERCENTAGE: bestdeals[bdkey] = bestdeals[bdkey] + '‼️'
            if sku['price'] > dbsku.price and sku['instock']:
                addMsg('📈 Повышение цены\n' + skustring + ' (было: ' + str(dbsku.price) + ' ' + dbsku.currency + ')')

            dbsku.instock = sku['instock']
            dbsku.price = sku['price']
            dbsku.errors = 0
            dbsku.lastgoodts = now
            stores[dbsku.store] = True
        else:
            dbsku.errors += 1
            if dbsku.store not in stores: stores[dbsku.store] = False

        dbsku.lastcheck = datetime.now().strftime('%d.%m.%Y %H:%M')
        dbsku.put()

    for chatid in msgs:
        try:
            paginatedTgMsg(msgs[chatid], chatid)
        except urllib2.HTTPError as e:
            if e.reason == 'Forbidden':
                disableUser(chatid)
        sleep(0.1)

    if BESTDEALSCHATID: paginatedTgMsg(bestdeals.values(), BESTDEALSCHATID)

    for store in stores:
        if not stores[store]: tgMsg('Problem with ' + store + '!', chat_id=ADMINCHATID)


def processCmd(message):
    text = message.get('text')
    message_id = message['message_id']
    chat_id = message['chat']['id']
    message_from = message.get('from')
    username = message_from.get('username')
    first_name = message_from.get('first_name')
    last_name = message_from.get('last_name')

    if text == '/start':
        processCmdStart(chat_id=chat_id, username=username, first_name=first_name, last_name=last_name)
        return

    if text == '/list':
        processCmdList(chat_id=chat_id)
        return

    if text.startswith('/add_'):
        processCmdAdd(cmd=text, chat_id=chat_id, message_id=message_id)
        return

    if text.startswith('/del_'):
        processCmdDel(cmd=text, chat_id=chat_id, message_id=message_id)
        return

    if text.startswith('/bc'):
        processCmdBroadcast(cmd=text, chat_id=chat_id)
        return

    if text == '/stat':
        processCmdStat(chat_id=chat_id)
        return

    tgMsg(msg='Непонятная команда 😧', chat_id=chat_id, reply_to=message_id)



def processCmdBroadcast(cmd, chat_id):
    if chat_id != ADMINCHATID: return
    return # full rewrite needed

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
        sleep(0.5)
    tgMsg(msg="Окончание рассылки", chat_id=chat_id)


def processCmdStat(chat_id):
    if chat_id != ADMINCHATID: return

    usersall = str(len(User.query().fetch()))
    users = str(len(User.query(User.enable == True).fetch()))
    userswsku = str(len(ndb.gql('SELECT DISTINCT chatid from SKU').fetch()))
    sku = str(len(SKU.query().fetch()))
    crc = str(len(SKU.query(SKU.store == 'CRC').fetch()))
    bc = str(len(SKU.query(SKU.store == 'BC').fetch()))
    b24 = str(len(SKU.query(SKU.store == 'B24').fetch()))
    bd = str(len(SKU.query(SKU.store == 'BD').fetch()))

    msg = ''
    msg += '<b>Total users:</b> ' + usersall + '\n'
    msg += '<b>Enabled users:</b> ' + users + '\n'
    msg += '<b>Users with SKU:</b> ' + userswsku + '\n'
    msg += '<b>Total SKU:</b> ' + sku + '\n'
    msg += '<b>CRC:</b> ' + crc + '\n'
    msg += '<b>BC:</b> ' + bc + '\n'
    msg += '<b>B24:</b> ' + b24 + '\n'
    msg += '<b>BD:</b> ' + bd + '\n'
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
                tgMsg(msg=data + '\n' + url, chat_id=ADMINCHATID)
        else:
            if offer.active:
                tgMsg(msg='ENDED: ' + offer.data + '\n' + url, chat_id=ADMINCHATID)
            offer.active = False

        offer.put()


class clearCacheHandler(webapp2.RequestHandler):
    def get(self):
        clearCacheVariants()

class removeOldSKUHandler(webapp2.RequestHandler):
    def get(self):
        removeOldSKU()


def getURL(store, prodid):
    entities = SKUcache.query(SKUcache.store == store, SKUcache.prodid == prodid).fetch()
    if entities:
        return entities[0].url
    return None


def sendOrEditMsg(msg, chat_id, message_id, msgtype):
    if msgtype == 'reply':
        tgMsg(msg=msg, chat_id=chat_id, reply_to=message_id)
    if msgtype == 'edit':
        tgEditMsg(text=msg, chat_id=chat_id, msg_id=message_id)


def addVariant(store, prodid, skuid, chat_id, message_id, msgtype):
    if len(SKU.query(SKU.chatid == chat_id).fetch()) >= MAXITEMSPERUSER:
        sendOrEditMsg('⛔️ Увы, в данный момент добавить можно не более ' + str(MAXITEMSPERUSER) + ' позиций', chat_id, message_id, msgtype)
        return

    entities = SKU.query(SKU.store == store, SKU.chatid == chat_id, SKU.prodid == prodid, SKU.skuid == skuid).fetch()
    if entities:
        sendOrEditMsg('️☝️ Товар уже есть в вашем списке', chat_id, message_id, msgtype)
        return

    url = getURL(store, prodid)
    if not url:
        sendOrEditMsg('Какая-то ошибка 😧', chat_id, message_id, msgtype)
        return

    variants = getVariants(store, url)
    if not variants or skuid not in variants:
        sendOrEditMsg('Какая-то ошибка 😧', chat_id, message_id, msgtype)
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
    dbsku.lastgoodts = int(time())
    dbsku.put()

    dispname = dbsku.variant
    if not dispname: dispname = dbsku.name

    sendOrEditMsg(dispname + '\n✔️ Добавлено к отслеживанию', chat_id, message_id, msgtype)


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
    tsnow = int(time()) - CACHELIFETIME * 60
    entities = SKUcache.query(SKUcache.timestamp < tsnow).fetch()
    for cache in entities:
        cache.key.delete()


def removeOldSKU():
    banner = 'ℹ️ Следующие позиции были удалены из вашего списка в связи с недоступностью более ' + str(ERRORMAXDAYS) + ' дней:'
    tsmax = int(time()) - ERRORMAXDAYS * 24 * 3600
    entities = SKU.query(SKU.lastgoodts < tsmax).fetch()
    msgs = {}
    for entity in entities:
        user = User.query(User.chatid == entity.chatid).fetch()[0]
        if user.enable:
            skustring = getSkuString(entity, ['store', 'url'])
            if entity.chatid not in msgs:
                msgs[entity.chatid] = [banner]
            msgs[entity.chatid].append(skustring)
        entity.key.delete()

    for chatid in msgs:
        try:
            paginatedTgMsg(msgs[chatid], chatid)
        except urllib2.HTTPError as e:
            if e.reason == 'Forbidden':
                disableUser(chatid)
        sleep(0.1)


def disableUser(chatid):
    user = User.get_or_insert(str(chatid))
    user.enable = False
    user.put()


def paginatedTgMsg(text_array, chat_id, message_id=0, delimiter='\n\n'):
    def sendOrEditMsg():
        if message_id != 0 and first_page:
            tgEditMsg(text=msg, chat_id=chat_id, msg_id=message_id)
        else:
            tgMsg(msg=msg, chat_id=chat_id)

    first_page = True
    msg = ''

    for paragraph in text_array:
        if len(msg + paragraph) > 4090:
            sendOrEditMsg()
            msg = ''
            first_page = False
        msg += paragraph + delimiter

    if msg: sendOrEditMsg()


app = webapp2.WSGIApplication([
    ('/', tgHandler),
    ('/checkprices', checkSKUHandler),
    ('/checkoffers', checkOffersHandler),
    ('/clearcache', clearCacheHandler),
    ('/removeoldsku', removeOldSKUHandler)
])
