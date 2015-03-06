#!/usr/bin/env python2.7

import requests
import sys
import time
import calendar
import json


class Item(object):
    '''
    Wrapper around a menu Item. Basically provides
    class like interface to the Item dictionary.
    '''
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def __repr__(self):
        return str(self.__dict__)


class Basket(object):
    '''
    Wrapper around the Basket dictionary returned from
    server. Provides class like access to Basket.
    '''
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def __repr__(self):
        return str(self.__dict__)


class Menu(object):
    '''
    Menu is a container for Items.
    '''
    def __init__(self):
        self.items = {}

    def addItem(self, category, item):
        '''
        Add an item of category to this menu.

        :param category: The category of this item. Usually item.Type
        :param item: The item to add

        '''

        self.items.setdefault(category, [])
        self.items[category].append(item)

    def itemsInCategory(self, category):
        try:
            return self.items[category]
        except:
            return []


class Dominos(object):
    '''
    Main class to interact with the dominos.co.uk
    site
    '''
    def __init__(self):
        self.sess = requests.session()
        self.base_url = 'https://www.dominos.co.uk/'
        self.stores = []
        self.menu_version = None
        self.menu = Menu()

        self.reset_session()

    def reset_session(self):
        '''
        Clear out a session by calling SessionExpire on the remote.
        Also clears out the local session and creates a new requests.session
        '''
        url = self.base_url + '/Home/SessionExpire'
        self.sess.get(url)
        self.sess = requests.session()

    def get_epoch(self):
        '''
        Utility function used to get current epoch time. Required for some
        calls to the remote.
        '''
        return calendar.timegm(time.gmtime())

    def search_stores(self, term):
        '''
        Given a search query returns all matching store objects.
        These are then stored in the stores list.
        Returns a list of stores as dictionaries. If no stores
        match ``term`` an empty list is returned.
        '''
        self.stores = []
        url = self.base_url + ('storelocatormap/storenamesearch')
        payload = {'search': term}
        results = self.sess.get(url, params=payload).json()

        for result in results:
            self.stores.append(result)

        return self.stores

    def select_store(self, idx):
        '''
        Return a store at the given index.
        '''
        return self.stores[idx]

    def get_cookie(self, store, postcode):
        '''
        Set local cookies by initialising the delivery system on the
        remote. Requires a store ID and a delivery postcode. This
        must be called once a store ID is known, as the generated cookies
        are needed for future calls.
        '''
        url = self.base_url + 'Journey/Initialize'
        payload = {'fulfilmentmethod': '1',
                   'storeId': store['Id'],
                   'postcode': postcode}

        self.sess.get(url, params=payload)

    def get_store_context(self):
        '''
        Get the required context for the store. This must be called at
        some point after get_cookie and before you are able to get a
        basket. This might fail due to possible rate limiting on the remote
        end. Some times waiting a little and retrying will make it succeed.
        '''
        url = self.base_url + 'ProductCatalog/GetStoreContext'
        payload = {'_': self.get_epoch()}
        headers = {'content-type': 'application/json; charset=utf-8'}
        r = self.sess.get(url, params=payload, headers=headers)

        try:
            context = r.json()
        except:
            return False

        self.menu_version = context['sessionContext']['menuVersion']
        return True

    def get_basket(self):
        '''
        Get the current basket object. get_store_context must be called first.
        May also fail, but will usually succeed if retried.
        '''
        url = self.base_url + '/Basket/GetBasket?'
        r = self.sess.get(url)

        try:
            self.basket = Basket(**(r.json()))
        except:
            return False
        return True

    def get_menu(self, store):
        '''
        Retrieve the menu for the currently set store. get_basket and
        get_store_context must be called successfully before this can be
        called.
        '''
        self.menu = Menu()
        if not self.menu_version:
            return None

        url = (self.base_url + '/ProductCatalog/GetStoreCatalog?'
               'collectionOnly=false&menuVersion=%s&storeId=%s' %
               (self.menu_version, store['Id']))
        r = self.sess.get(url)

        idx = 0
        for item in r.json():
            for i in item['Subcategories']:
                for p in i['Products']:
                    p['idx'] = idx
                    self.menu.addItem(i['Type'], Item(**p))
                    idx += 1

        return self.menu

    def add_item(self, item, size_idx):
        '''
        Add an item to the basket. Provide the item object and
        a size index. Will overwrite the basket with the new basket.

        :param item: The item instance you want to add to the basket
        :param size_idx: The index into the item`s available sizes.
        '''

        url = self.base_url

        if item.Type == 'Pizza':
            url += '/Basket/AddPizza/'
            ingredients = item.ProductSkus[size_idx]['Ingredients']

            # always cheese and tomato sauce
            ingredients += [42, 36]

            payload = {"stepId": 0,
                       "quantity": 1,
                       "sizeId": size_idx,
                       "productId": item.ProductId,
                       "ingredients": ingredients,
                       "productIdHalfTwo": 0,
                       "ingredientsHalfTwo": [],
                       "recipeReferrer": 0}
        elif item.Type == 'Side':
            url += '/Basket/AddProduct/'
            sku_id = item.ProductSkus[size_idx]['ProductSkuId']

            payload = {"ProductSkuId": sku_id,
                       "Quantity": 1,
                       "ComplimentaryItems": []}

        headers = {'content-type': 'application/json; charset=utf-8'}
        r = self.sess.post(url, data=json.dumps(payload), headers=headers)

        if r.status_code != 200:
            return False

        try:
            self.basket = Basket(**r.json())
        except:
            return False

        return True

    def remove_item(self, basket_item_idx):
        '''
        Remove an item at basket position item_idx from the basket
        '''
        item = Item(**self.basket.Items[basket_item_idx])

        # https://www.dominos.co.uk/Basket/RemoveBasketItem/?basketItemId=3&wizardItemDelete=false
        url = self.base_url + '/Basket/RemoveBasketItem'
        payload = {'basketItemId': item.BasketItemId,
                   'wizardItemDelete': False}

        r = self.sess.get(url, params=payload)
        if r.status_code != 200:
            print('[Error] Connection failed to remove item.')
            return

        try:
            self.basket = Basket(**r.json())
        except:
            print('[Error] Error removing item. Invalid response.')
            return

        print(u'[OK] Removed %s' % item.Title)


if __name__ == '__main__':
    d = Dominos()
    stores = d.search_stores(sys.argv[1])

    valid = False
    store = 0
    while(not valid):
        print 'Select a store:'
        for i, s in enumerate(stores):
            print '[%d] %s' % (i, s['Name'])

            store = int(raw_input('Store: '))
            store = d.select_store(store)
            if store:
                valid = True

    postcode = raw_input('Enter your postcode: ')
    d.get_cookie(store, postcode)
    time.sleep(2)

    doit = True
    while not d.get_store_context() and doit:
        a = raw_input('carry on?')
        if a == 'n':
            doit = False
        d.reset_session()

    doit = True
    while not d.get_basket() and doit:
        a = raw_input('carry on?')
        if a == 'n':
            doit = False

    d.get_menu(store)

    d.show_menu()
