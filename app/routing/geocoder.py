from geopy.geocoders import Nominatim

geolocator = Nominatim(user_agent="traffic-ai")

def get_coordinates(location):

    loc = geolocator.geocode(location)

    if loc:
        return (loc.latitude, loc.longitude)

    return None