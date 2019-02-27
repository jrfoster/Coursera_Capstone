from bs4 import BeautifulSoup
from fastnumbers import fast_real
import requests
import pandas as pd

def clean_value(value):
   '''
    Utility function to format certain piecesof demographc data that include 
    formatting characters and percentages which can be calculated otherwise.

    Takes the first word in a sentence, removes commas and dollar signs and strips
    any leading and trailing spaces.
    
    Keyword Arguments
    value -- A string to clean
    '''     
    return value.split()[0].replace(',','').replace('$','').strip()

def scrape_zipcodes():
   '''
    Scrapes the zip code list located on zip-codes.com for the city and county of
    Denver
   '''
    zips_raw = requests.get('https://www.zip-codes.com/county/co-denver.asp').text
    soup = BeautifulSoup(zips_raw, 'lxml')
    
    # On the page, the data we want is located in a table with class 'statTable'.
    # The table shows zip codes for places where people don't actually live, so
    # we only grab the 'general' zip codes
    l = []
    rows = soup.find('table', {"class": "statTable"}).findAll('tr') 
    for row in rows:
        cells = row.findAll("td")
        zipcode = cells[0].get_text().split()[-1]
        classification = cells[1].get_text().strip()
        if (zipcode.isdigit() and classification == 'General'):
            l.append(zipcode)  

    # Now we convert the data to a dataframe and return it
    return pd.DataFrame(l, columns=['Zip Code'])

def scrape_demographics(zipcode, prefix='colorado', missingZip=80202):
   '''
    Scrapes demographic information for a zip code from hometownlocator

    Keyword Arguments
    zipcode - The zip code to scrape
    prefix - The state in which the zip code is located. Default is colorado
    missingZip - If demographic data is not found, which zip code to use instead 
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

def get_latlon(place):
   '''
    Uses the Google API to retrieve location information. Note that the API key has been scrubbed

    Keyword Arguments
    place - The location to geocode. can be an address, zip code, state, etc.
   '''
    API_KEY = '<<removed>>'
    url = 'https://maps.googleapis.com/maps/api/geocode/json?address={}&key={}'.format(
        place,
        API_KEY
    )
    response = requests.get(url).json()
    address = response['results'][0]['formatted_address']
    latlon = response['results'][0]['geometry']['location']
    return latlon['lat'], latlon['lng']

def explore_location(lat, lon, limit=100):
    '''
    Utilizes the Foursquare API to return top 100 venues near the given coordinates
    
    Keyword Arguments:
    lat -- the latitude of the location
    lon -- the longitude of the location
    limit -- The optional limit on the number of results. Default is 100
    '''
    CLIENT_ID = 'TBXKQI4YUWMBMOYKP3UUGJ1DMGIZ1MXYKC0BDWK2M4VIQAPD' 
    CLIENT_SECRET = '<<removed>>'
    VERSION = '20190101'
    
    # Get the top 100 venues in this postal code from the Foursquare API and transform
    # the results into a DataFrame. We are excluding radius from the request, as the API
    # will suggest a radius based on the density of venues in the area    
    url = 'https://api.foursquare.com/v2/venues/explore?client_id={}&client_secret={}&v={}&ll={},{}&limit={}'.format(
        CLIENT_ID, 
        CLIENT_SECRET, 
        VERSION, 
        lat, 
        lon, 
        limit)
    return requests.get(url).json()

def getNearbyVenues(names, latitudes, longitudes):
    '''
    Uses the Foursquare API to get the top 100 venues near the given coordinates
    
    Keyword Arguments
    names -- A sequence of names for display purposes
    latitudes -- A sequence of latitudes to lookup
    longitudes -- A sequence of longitudes to lookup
    '''     
    venues_list=[]
    for name, lat, lng in zip(names, latitudes, longitudes):
        # create the API request URL
        results = explore_location(lat, lng)
        
        # The actual results are in the items array of groups
        groups = results['response']['groups'][0]['items']
        
        # Return only relevant information for each nearby venue
        venues_list.append([(
            name, 
            lat, 
            lng, 
            v['venue']['name'], 
            v['venue']['location']['lat'], 
            v['venue']['location']['lng'],  
            v['venue']['categories'][0]['name']) for v in groups])

    nearby_venues = pd.DataFrame([item for venue_list in venues_list for item in venue_list])
    nearby_venues.columns = ['Neighborhood', 
                  'Neighborhood Latitude', 
                  'Neighborhood Longitude', 
                  'Venue', 
                  'Venue Latitude', 
                  'Venue Longitude', 
                  'Venue Category']
    
    return(nearby_venues)