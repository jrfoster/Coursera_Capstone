'''
This file contains most of the code for the IBM Applied Data Science Capstone
project. It houses utility functions for scraping data from HTML pages, 
geolocating zip codes and other places using the Google Maps API, and obtains
venue and category data from the Foursquare API. Other functions in this file 
do some data manipulation and scrubbing as well

Author: Jason R. Foster

Portions of this library adapted from information obtained from the following 
sources:

* IBM Applied Data Science Foursquare Lab (course materials)
* Pandas Documentation https://pandas.pydata.org/pandas-docs/stable/
* Anytree Documentation https://anytree.readthedocs.io/en/latest/
* Simpsons Diversity Index http://www.countrysideinfo.co.uk/simpsons.htm
* Google Maps API https://developers.google.com/maps/documentation/geocoding/start
''' 
import redacted as rg               # Contains the API keys and secrets, not in source control
from bs4 import BeautifulSoup       # For parsing HTML responses during scraping
from fastnumbers import fast_real   # For smart creation of integers or floaats from strings
import requests                     # For making http requests during scraping
import pandas as pd                 # Dataframes and other list operations
import numpy as np                  # Various numerical and mathematical utilities
import os                           # For determining current working directory
from time import sleep              # To allow for a sleep during retries of http requests
import pickle                       # Serialization for dataframes to avoid request caps
import urllib.parse                 # For url-encoding query strings, mostly for Google
from anytree import Node, search    # Fast tree implementation for Foursquare categories
from selenium import webdriver      # Used only for saving png versions of Folium maps
import logging                      # For saving output from what I would normally print

# Go ahead and configure the logger, since this module will be run when its loaded
logging.basicConfig(filename='capstone_util.log', filemode='w', level=logging.DEBUG)

def clean_value(value):
    '''
    Utility function to format certain pieces of demographic data that include 
    formatting characters and percentages which can be calculated otherwise.

    Takes the first word in a sentence, removes commas and dollar signs and strips
    any leading and trailing spaces.

    Keyword Arguments:
    value -- A string to clean
    '''
    return value.split()[0].replace(',','').replace('$','').strip()

def save_map(map, html_fn, png_fn, html_dir='maps', delay=3):
    '''
    Uses the Selenium driver (geckodriver.exe) to save the rendered folium map
    as a png image
    
    Keyword Arguments:
    map -- The rendered folium map to save
    html_fn -- The HTML filename to use when saving the rendered map
    png_fn -- The PNG filename, including path, to use when saving the image
    html_dir -- A subdirectory to use when saving the HTML. Default is 'maps'
    delay -- The number of seconds to sleep to allow Selenium to capture
    '''
    # Save the map as an HTML file
    tmpurl = 'file://{cwd}/{subdir}/{file}'.format(cwd=os.getcwd(), subdir=html_dir, file=html_fn)
    map.save('{cwd}/{subdir}/{file}'.format(cwd=os.getcwd(), subdir=html_dir, file=html_fn))
     
    # Open a browser window that displays the map, wait for it to load
    # then grab a screenshot
    browser = webdriver.Firefox()
    browser.get(tmpurl)
    sleep(delay)
    browser.save_screenshot(png_fn)
    browser.quit()    


def add_categories(cats, r):
    '''
    Recursively builds a tree of categories from foursquare. This tree can
    be used to find specific ancestors of any given category
    
    Keyword Arguments:
    cats -- Json array of categories from the Foursquare API
    r -- Current node in which to add children, if any
    '''
    for cat in cats:
        n = Node(name=cat['id'], parent=r, descr=cat['name'])
        if len(cat['categories']) > 0:
            add_categories(cat['categories'], n)
            
    return n 


def get_category_tree(trycount=0):
    '''
    Utilizes the Foursquare API to return their tree of categories. This method
    uses anytree and returns a root node with all the hierarchy of categories
    listed on https://developer.foursquare.com/docs/resources/categories
    
    Keyword Arguments:
    trycount -- the count of current tries, for retry. Default is 0
    '''
    logger = logging.getLogger('capstoneutils.get_category_tree')
    VERSION = '20190101'
    
    # Retrieve the categories from Foursquare  
    url = 'https://api.foursquare.com/v2/venues/categories?client_id={}&client_secret={}&v={}'.format(
        rg.CLIENT_ID, 
        rg.CLIENT_SECRET, 
        VERSION)
    
    result = requests.get(url).json()
    if (result['meta']['code'] != 200 and trycount < 5):
        sleep(0.5)
        t = trycount + 1
        logger.warning('Retrying Foursquare CATEGORY due to failure. Trycount={}'.format(t))
        return get_category_tree(trycount=t)
    
    cats = result['response']['categories']
    root = Node('root')
    add_categories(cats, root)
    return root


def get_top_parent(tree, name):
    '''
    Searches the given anytree tree for a node with the given name and returns
    the ancestor just under root, which would be the top-level category from
    Foursquare categories https://developer.foursquare.com/docs/resources/categories
    
    Keyword Arguments:
    tree -- The anytree tree to search for the top parent
    name -- The name to search the tree for
    '''
    node = search.findall(tree, filter_ = lambda node:  node.name == name)[0]
    if len(node.ancestors) == 1:
        # This is already a top-level candidate so return it
        return node
    else:
        return node.ancestors[1]


def scrape_zipcodes(page_dict):
    '''
    Scrapes the zip code list located on zip-codes.com for the city and county of
    Denver

    Keyword Arguments:
    page_dict -- a dictionary containing the url (key) and list of cities to scrape
    '''
    l = []

    for url, cities in page_dict.items():
        zips_raw = requests.get(url).text
        soup = BeautifulSoup(zips_raw, 'lxml')

        # On the page, the data we want is located in a table with class 'statTable'.
        # The table shows zip codes for places where people don't actually live, so
        # we only grab the 'general' zip codes
        rows = soup.find('table', {"class": "statTable"}).findAll('tr') 
        for row in rows:
            cells = row.findAll("td")
            zipcode = cells[0].get_text().split()[-1]
            classification = cells[1].get_text().strip()
            city = cells[2].get_text().strip()
            if (zipcode.isdigit() and classification == 'General' and city in cities):
                l.append(zipcode)  

    # Now we convert the data to a dataframe and return it
    return pd.DataFrame(l, columns=['ZipCode'])


def scrape_demographics(zipcode, prefix='colorado', missingZip='80202'):
    '''
    Scrapes demographic information for a zip code from hometownlocator

    Keyword Arguments:
    zipcode -- The zip code to scrape
    prefix -- The state in which the zip code is located. Default is colorado
    missingZip -- If demographic data is not found, which zip code to use instead 
    '''
    demo_raw = requests.get('https://{}.hometownlocator.com/zip-codes/data,zipcode,{}.cfm'.format(prefix, zipcode)).text

    soup = BeautifulSoup(demo_raw, 'lxml')
    
    # On this page the data we are looking for is in two divs both with a class 
    # of 'halfcontentpadded'. Each div contains a table with a header row that
    # has colspan of 2 and then tr's with two td's the first with a span that
    # holds the label and the second holding the actual data. Overall this will
    # build out a demographics dataframe of 20 columns
    data = {"ZipCode": zipcode}
    divs = soup.findAll('div', {"class": "halfcontentpadded"})
    
    # There isn't demographic data available for all the zip codes. From inspection,
    # the site we are using for demographics suggests 80202 for all the ones that
    # are missing, so we use that data instead. Note that this will result in duplicates
    # which are easily removed later.
    if (len(divs) < 3):
        return scrape_demographics(missingZip)
    
    for i in [1,2]:
        div = divs[i]
        rows = div.find('table').findAll('tr')
        for row in rows:
            cells = row.findAll('td')
            if not cells or cells[0].has_attr('colspan'):
                continue
            key = cells[0].find('span').get_text().strip()
            value = clean_value(cells[1].get_text().strip())
            data[key] = fast_real(value)
    
    # Return the dictionary of values
    return data


def scrape_franchises():
    '''
    Scrapes the wikipedia page with the list of coffee franchises. The data is in the first
    table with the wikitable sortable style. This code pulls out just the first column.
    '''
    url = 'https://en.wikipedia.org/wiki/List_of_coffeehouse_chains'
    df_cols = ['Name']

    try:
        html_raw = requests.get(url).text
        soup = BeautifulSoup(html_raw, 'lxml')
        table = soup.find('table', {'class': ['wikitable', 'sortable', 'jquery-sortable']})
        rows = table.find_all('tr')
        l = []
        for row in rows:
            td = row.find_all('td')
            cells = [cell for cell in td]
            if len(cells) > 0:
                l.append(cells[0].find('a').get_text())
        return pd.DataFrame(l, columns=df_cols)

    except:
        return pd.DataFrame(columns=df_cols)

def get_place_latlon(place, trycount=0):
    '''
    Uses the Google API to retrieve location information. Note that the API key has been scrubbed

    Keyword Arguments:
    place -- The place to geolocate
    '''
    logger = logging.getLogger('capstoneutils.get_place_latlon')
    url = 'https://maps.googleapis.com/maps/api/geocode/json?address={}&key={}'.format(
        urllib.parse.quote_plus(place),
        rg.GOOGLE_API_KEY
    )
    
    response = requests.get(url).json()
    
    if len(response['results']) == 0 and trycount < 5:
        sleep(.05)
        t = trycount + 1
        logger.warning('Retrying Google Maps GEOCODE due to failure. Trycount={}'.format(t))
        return get_place_latlon(place, trycount=t)
    
    latlon = response['results'][0]['geometry']['location']
    return [latlon['lat'], latlon['lng']]


def get_latlon(x):
    '''
    Uses the Google API to retrieve location information. Note that the API key has been scrubbed

    Keyword Arguments:
    x -- The row containing the ZipCode to geolocate, must be a string zip code
    '''
    return get_place_latlon(x['ZipCode'])


def explore_location(lat, lon, limit=100, section=None, trycount=0):
    '''
    Utilizes the Foursquare API to return top 100 venues near the given coordinates

    Keyword Arguments:
    lat -- the latitude of the location
    lon -- the longitude of the location
    limit -- The optional limit on the number of results. Default is 100
    '''
    logger = logging.getLogger('capstoneutils.explore_location')
    VERSION = '20190101'
    
    # Get the top 100 venues in this postal code from the Foursquare API and transform
    # the results into a DataFrame. We are excluding radius from the request, as the API
    # will suggest a radius based on the density of venues in the area    
    url = 'https://api.foursquare.com/v2/venues/explore?client_id={}&client_secret={}&v={}&ll={},{}&limit={}'.format(
        rg.CLIENT_ID, 
        rg.CLIENT_SECRET, 
        VERSION, 
        lat, 
        lon, 
        limit)
    
    if section:
        url = url + '&section={}'.format(section)
    
    result = requests.get(url).json()
    if (result['meta']['code'] != 200 and trycount < 5):
        sleep(0.5)
        t = trycount + 1
        logger.warning('Retrying Foursquare EXPLORE due to failure. Trycount={}'.format(t))
        return explore_location(lat, lon, limit, section, trycount=t)

    return requests.get(url).json()


def get_nearby_venues(rownames, latitudes, longitudes, section=None):
    '''
    Uses the Foursquare API to get the top 100 venues near the given coordinates

    Keyword Arguments:
    names -- A sequence of names intended to help later identify rows
    latitudes -- A sequence of latitudes to lookup
    longitudes -- A sequence of longitudes to lookup
    '''
    venues_list=[]
    category_tree = get_category_tree()
    
    for name, lat, lng in zip(rownames, latitudes, longitudes):
        # create the API request URL
        results = explore_location(lat, lng, section=section)
        
        # The actual results are in the items array of groups
        groups = results['response']['groups'][0]['items']
        
        # Return relevant information for each nearby venue.
        for v in groups:
            cat = v['venue']['categories'][0]
            c_main = cat['name']
            c_top = get_top_parent(category_tree, cat['id']).descr
            
            venues_list.append([(
                name, 
                lat, 
                lng, 
                v['venue']['name'], 
                v['venue']['location']['lat'], 
                v['venue']['location']['lng'],
                c_main,
                c_top)])
    
            nearby_venues = pd.DataFrame([item for venue_list in venues_list for item in venue_list])
            nearby_venues.columns = [
                'ZipCode', 
                'Centroid Latitude', 
                'Centroid Longitude', 
                'Venue', 
                'Venue Latitude', 
                'Venue Longitude', 
                'Venue Main Category',
                'Venue Top-Level Category']
    
    return(nearby_venues)


def return_most_common_venues(row, num_top_venues=10):
    '''
    Returns the requested number of top results from a pandas DataFrame row of numerical values
    
    Keyword Arguments:
    row -- The DataFrame row from which to obtain the top results
    num_top_venues -- The number of items to return. Default value is 10.
    '''
    row_categories = row.iloc[1:]
    row_categories_sorted = row_categories.sort_values(ascending=False)
    
    return row_categories_sorted.index.values[0:num_top_venues]


def get_category_type(row):
    '''
    Returns the category of a venue from a row of data returned from 
    Foursquare, or None if one cannot be found
    
    Keyword Arguments:
    row -- the Pandas DataFrame row from which to extract the category
    ''' 
    try:
        categories_list = row['categories']
    except:
        categories_list = row['venue.categories']
        
    if len(categories_list) == 0:
        return None
    else:
        return categories_list[0]['name']


def load_demographics():
    '''
    Does the heavy lifting of loading the pre-done demographics from a serialized
    version or builds it from scratch using the utility methods in this library
    '''
    logger = logging.getLogger('capstoneutils.load_demographics')
    demog_file = './all_demog.pkl'
    loaded = False
    try:
        with open(demog_file, 'rb') as f:
            logger.info("Geocoding: Using pickled demographics/geocoding.")
            results = pickle.load(f)
        loaded = True

    except:
        pass

    if not loaded:
        logger.info('Building demographics/geocoding data from scratch. Please be patient.')
        # Scrape the pages with the lists of zip codes for the Denver metro area
        pages = {
            'https://www.zip-codes.com/county/co-denver.asp': ['Denver']
            ,'https://www.zip-codes.com/county/co-adams.asp': ['Denver','Westminster','Aurora','Thornton']
            ,'https://www.zip-codes.com/county/co-jefferson.asp': ['Arvada','Broomfield','Wheat Ridge','Littleton','Denver','Golden']
            ,'https://www.zip-codes.com/county/co-arapahoe.asp': ['Aurora','Englewood','Littleton']
            ,'https://www.zip-codes.com/county/co-douglas.asp': ['Castle Rock','Lone Tree','Littleton','Parker']
            ,'https://www.zip-codes.com/county/co-boulder.asp': ['Boulder']
        }

        den_zips = scrape_zipcodes(pages)
        logger.info('ZipCodes: Successfully scraped {} zip codes.'.format(den_zips.shape[0]))

        # Scrape the other pages for demographics for each zip code in the list
        l = []
        for zipcode in den_zips['ZipCode']:
            l.append(scrape_demographics(zipcode))
        l.append(scrape_demographics('85281', 'arizona'))
        results = pd.DataFrame(l)
        results['ZipCode'] = results['ZipCode'].astype(str)
        
        # We drop three zip codes, two because their demographihcs are all zeroes and one
        # because its a tiny part of a medical school campus. We then drop any duplicates.
        results.drop(results[results.ZipCode == '80294'].index, inplace=True)
        results.drop(results[results.ZipCode == '80225'].index, inplace=True)
        results.drop(results[results.ZipCode == '80045'].index, inplace=True)
        results.drop_duplicates('ZipCode', keep='first', inplace=True)
        logger.info("Demographics: Successfully scraped {} features for {} Zip Codes".format(results.shape[1], results.shape[0]))
        
        # Geolocate the zip codes using the Google API
        results[['Latitude', 'Longitude']] = results.apply(lambda row: pd.Series(get_latlon(row)), axis=1)
        logger.info("Geocoding: Successfully geocoded {} Zip Codes".format(results.shape[0]))

        # Reorder the columns and pickle the results        
        results = results[['ZipCode','Latitude', 'Longitude'] + [c for c in results if c not in ['ZipCode','Latitude', 'Longitude']]]
        results.to_pickle(demog_file)
        
    return results


def load_foursquare_venues(names, lats, lngs):
    '''
    Does the heavy lifting to get the venue data from Foursquare or from a file if
    its already been retrieved. The method takes three sequences as paramenters, 
    though it might be easier to think of the parameters as a lists of tuples, one
    for each request that is made to Foursquare.
    
    Keyword Arguments:
    names -- A sequence of rownames to use for each request
    lats -- A sequence of latitudes to use for each request
    lngs -- A sequence of longitudes to use for each request
    '''
    logger = logging.getLogger('capstoneutils.load_foursquare_venues')
    venue_file = './fsq_venues.pkl'
    loaded = False
    
    try:
        with open(venue_file, 'rb') as f:
            logger.info("Using pickled venue data.")
            result_venues = pickle.load(f)
        loaded = True
        
    except:
        pass
    
    if not loaded:
        logger.info('Building Foursquare venue data from scratch. Please be patient.')
        result_venues = get_nearby_venues(rownames=names, latitudes=lats, longitudes=lngs)
        gp = result_venues.groupby(by='ZipCode').count()
        logger.info("Top Venues: Successfully retrieved {} features for {} Zip Codes.".format(gp.shape[1], gp.shape[0]))
        
        result_venues.to_pickle(venue_file)

    return result_venues


def load_coffee_shops(names, lats, lngs):
    '''
    Does the heavy lifting to get the coffee venue data from Foursquare or from a file if
    its already been retrieved. The method takes three sequences as paramenters, 
    though it might be easier to think of the parameters as a lists of tuples, one
    for each request that is made to Foursquare.
    
    Keyword Arguments:
    names -- A sequence of rownames to use for each request
    lats -- A sequence of latitudes to use for each request
    lngs -- A sequence of longitudes to use for each request
    '''
    logger = logging.getLogger('capstoneutils.load_coffee_shops')
    coffee_file= './fsq_coffee.pkl'
    loaded = False
    
    try:
        with open(coffee_file, 'rb') as f:
            logger.info("Using pickled coffee shop data")
            results = pickle.load(f)
        loaded = True
    
    except:
        pass
    
    if not loaded:
        logger.info("Building Foursquare coffee shop data from scratch. Please be patient.")
        # Get the shops from the candidates using Foursquare EXPLORE with a section = 'coffee'
        # then create and sort a pivot table showing the counts with the margin totals calculated
        candidate_shops = get_coffee_shops(rownames=names,latitudes=lats,longitudes=lngs)
        grouped_shops = candidate_shops.groupby(['ZipCode','IsFranchise'], as_index=False)['Venue'].count()
        results = pd.pivot_table(grouped_shops, index='ZipCode', columns='IsFranchise', values='Venue', aggfunc='sum', margins=True, fill_value=0)
        results.reset_index(inplace=True)
        results = results[:-1]
        results[['PctInd']] = results.apply(lambda row: pd.Series(row['False'] / row['All']), axis=1)
        
        results.to_pickle(coffee_file)
    
    return results


def get_top_venues(result_venues, num_top_venues=10):
    '''
    Uses the method shown in the Foursquare lab to generate the top n venues for each zip
    code in the passed dataframe.
    
    Keyword Arguments:
    result_venues -- Dataframe containg the venue data. Must contain at least a ZipCode
                     and Venue Main Category column
    num_top_venues -- The number of venues to return. Default is 10
    '''
    # Perform one hot encoding
    onehot = pd.get_dummies(result_venues[['Venue Main Category']], prefix="", prefix_sep="")
    
    # Add back our zip code column and group the data by zip code
    # and drop the noted features
    onehot['ZipCode'] = result_venues['ZipCode']
    
    onehot_grouped = onehot.groupby('ZipCode').mean().reset_index()
    
    # Create columns according to number of top venues by exhausting the special suffix
    # list 'indicators' and using the same suffix for items 3-10.
    indicators = ['st', 'nd', 'rd']
    columns = ['ZipCode']
    for ind in np.arange(num_top_venues):
        try:
            columns.append('{}{} Most Common Venue'.format(ind+1, indicators[ind]))
        except:
            columns.append('{}th Most Common Venue'.format(ind+1))
    
    # Create a new dataframe with the derived column names and our zip codes
    result_venues_sorted = pd.DataFrame(columns=columns)
    result_venues_sorted['ZipCode'] = onehot_grouped['ZipCode']
    
    # For each zip code, use our utility function to get the top 10 venue categories
    for ind in np.arange(onehot_grouped.shape[0]):
        result_venues_sorted.iloc[ind, 1:] = return_most_common_venues(onehot_grouped.iloc[ind, :], num_top_venues)
    
    return result_venues_sorted

def is_franchise(x, fr_list):
    '''
    Uses the given list to determine if the row representing a venue is a franchise or not.
    Intended to be used with apply.
    
    Keyword Arguments:
    x -- Row containing a venue name to determine whether its a franchise or not
    fr_list -- The list of venues to compare with
    '''
    isFranchise = 'False'
    orig_name = x['Venue']
    name = orig_name.split('(')[0].split('#')[0].strip()
    
    # Deal with a couple of anomalies in the data we are returning
    fw = name.split(' ')[0].strip()
    if fw == 'Starbucks':
        name = fw
    if fw == 'Dunkin\'Donuts':
        name = 'Dunkin\' Donuts'
        
    if name in fr_list:
        isFranchise = 'True'
    
    return [isFranchise]

def get_coffee_shops(rownames, latitudes, longitudes):
    '''
    Utilizes the Foursquare EXPLORE endpoint with a section parameter to obtain a recommended
    list of coffee shops for the given places
    
    Keyword Arguments:
    rownames -- A sequence of names intended to help later identify rows
    latitudes -- A sequence of latitudes to lookup
    longitudes -- A sequence of longitudes to lookup
    '''
    franchises = scrape_franchises()
    fr_vals = franchises['Name'].values
    
    candidate_cs = get_nearby_venues(rownames=rownames,
                                     latitudes=latitudes,
                                     longitudes=longitudes,
                                     section='coffee')
    
    # Foursquare's 'coffee' section returns a few things that are not 
    # just coffee shops, so I'm only keeping the ones that are
    candidate_cs.drop(candidate_cs[~candidate_cs['Venue Main Category'].isin(['Coffee Shop'])].index, inplace=True)
    
    # Add a column that says whether the venue is a franchise based
    # on the list we sraped from Wikipedia
    candidate_cs[['IsFranchise']] = candidate_cs.apply(lambda row: pd.Series(is_franchise(row, fr_vals)), axis=1)
   
    return candidate_cs
        
def get_nextvenues(trycount=0):
    '''
    Returns the top 5 most commonly visited venues for my venue
    '''
    logger = logging.getLogger('capstoneutils.get_nextvenues')
    VERSION = '20190101'
    
    # Get the top 100 venues in this postal code from the Foursquare API and transform
    # the results into a DataFrame. We are excluding radius from the request, as the API
    # will suggest a radius based on the density of venues in the area
    url = 'https://api.foursquare.com/v2/venues/{}/nextvenues?client_id={}&client_secret={}&v={}'.format(
        rg.MY_VENUE,
        rg.CLIENT_ID, 
        rg.CLIENT_SECRET, 
        VERSION)
    
    results = requests.get(url).json()
    if (results['meta']['code'] != 200 and trycount < 5):
        sleep(0.5)
        t = trycount + 1
        logger.warning('Retrying Foursquare NEXTVENUES due to failure. Trycount={}'.format(t))
        return get_nextvenues(trycount=t)
    
    venues_list=[]
    items = results['response']['nextVenues']['items']
    
    for i in items:
        venues_list.append([(
            i['name'],
            i['categories'][0]['name'],
            i['location']['lat'],
            i['location']['lng'])])     
        
        next_venues = pd.DataFrame([item for venue_list in venues_list for item in venue_list])
        
        next_venues.columns = [
            'Venue', 
            'Venue Main Category',
            'Venue Latitude', 
            'Venue Longitude']
    
    return(next_venues)
