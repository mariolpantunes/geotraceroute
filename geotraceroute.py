#!/usr/bin/env python3
# coding: utf-8


__author__ = 'Mário Antunes'
__version__ = '0.1'
__email__ = 'mario.antunes@ua.pt'
__status__ = 'Development'
__license__ = 'MIT'


import os
import json
import time
import logging
import pathlib
import argparse
import datetime
import requests
import ipaddress
import subprocess


import cartopy
import cartopy.crs as ccrs
import matplotlib.pyplot as plt


logging.basicConfig(level=logging.INFO, format='%(message)s')
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def valid_public_ip(address):
    try:
        if not ipaddress.ip_address(address).is_private:
            return True
        else:
            return False
    except:
        return False


def get_public_ip():
    ip = requests.get('https://api.ipify.org').content.decode('utf8')
    return ip


def hex_to_RGB(hex):
  ''' "#FFFFFF" -> [255,255,255] '''
  # Pass 16 to the integer function for change of base
  return [int(hex[i:i+2], 16) for i in range(1,6,2)]


def RGB_to_hex(RGB):
  ''' [255,255,255] -> "#FFFFFF" '''
  # Components need to be integers for hex to make sense
  RGB = [int(x) for x in RGB]
  return "#"+"".join(["0{0:x}".format(v) if v < 16 else
            "{0:x}".format(v) for v in RGB])


def linear_gradient(start_hex, finish_hex="#FFFFFF", n=10):
  ''' returns a gradient list of (n) colors between
    two hex colors. start_hex and finish_hex
    should be the full six-digit color string,
    inlcuding the number sign ("#FFFFFF") '''
  # Starting and ending colors in RGB form
  s = hex_to_RGB(start_hex)
  f = hex_to_RGB(finish_hex)
  # Initilize a list of the output colors with the starting color
  RGB_list = [s]
  # Calcuate a color at each evenly spaced value of t from 1 to n
  for t in range(1, n):
    # Interpolate RGB vector for color at the current value of t
    curr_vector = [
      int(s[j] + (float(t)/(n-1))*(f[j]-s[j]))
      for j in range(3)
    ]
    # Add it to our list of output colors
    RGB_list.append(curr_vector)

  return RGB_list


def resolve_ip(ip, cache_file_path):
    """
    Resolves an IP address to latitude and longitude, using a local JSON cache
    to avoid repeated API calls.

    Optimizations:
    1. Uses float timestamps for date comparison (much faster than string parsing).
    2. Handles FileNotFoundError and corrupt JSON data gracefully.
    3. Handles network errors (requests.RequestException).
    4. Checks API response for 'status' field to ensure a valid result.
    5. Uses a single return statement.
    """

    # This will be the single value returned at the end.
    # Default to (ip, None, None) in case of any failure.
    result = (ip, None, None)

    cache = {}
    cache_ttl_seconds = 3600  # 1 hour

    current_timestamp = datetime.datetime.now().timestamp()
    cache_hit_fresh = False

    # --- 1. Load Cache ---
    # Optimized: Added robust error handling for missing or corrupt cache file.
    with open(cache_file_path, 'r') as f:
        cache = json.load(f)

    # --- 2. Check Cache ---
    if ip in cache:
        try:
            # Optimized: Compare float timestamps. This is significantly
            # faster than parsing a datetime string on every call.
            is_fresh = (current_timestamp - cache[ip]['timestamp']) < cache_ttl_seconds

            if is_fresh:
                logger.debug(f'CACHE HIT: {cache[ip]}')
                # Set the result from cached data
                result = (ip, cache[ip]['lat'], cache[ip]['lon'])
                cache_hit_fresh = True

        except (KeyError, TypeError):
            # Cache entry is malformed (e.g., missing 'timestamp' or wrong type)
            # We will treat it as a cache miss and overwrite it.
            pass

    # --- 3. Fetch from API (if cache miss or stale) ---
    if not cache_hit_fresh:
        logger.debug(f'CACHE MISS: Fetching {ip} from API...')
        try:
            time.sleep(0.15)
            response = requests.get(f'http://ip-api.com/json/{ip}')
            # Raise an exception for bad HTTP status codes (4xx or 5xx)
            response.raise_for_status()
            response_json = response.json()

            # Optimized: Check for API-level failure (e.g., 'private range')
            # The API can return 200 OK but still have a 'fail' status.
            if response_json.get('status') == 'success':
                lat = response_json['lat']
                lon = response_json['lon']

                # Set the result from the fresh API data
                result = (ip, lat, lon)

                # Update the cache dictionary
                cache[ip] = {
                    'ip': ip,
                    'lat': lat,
                    'lon': lon,
                    'timestamp': current_timestamp
                }

                # --- 4. Write Cache Back ---
                try:
                    with open(cache_file_path, 'w') as f:
                        json.dump(cache, f, indent=4)
                except IOError as e:
                    logger.error(f'Warning: Could not write to cache file: {e}')

            else:
                logger.error(f'API Error for {ip}: {response_json.get('message')}')

        except requests.RequestException as e:
            # Handles connection errors, timeouts, bad HTTP status, etc.
            logger.error(f"Network or HTTP Error for {ip}: {e}")

    # --- 5. Single Return Statement ---
    return result


def main(url, cache_file_path):
    if 'container' in os.environ:
        command = f'flatpak-spawn --host traceroute -n -F -w 1 {url}'
    else:
        command = f'traceroute -n -F -w 1 {url}'

    try:
        result = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT).decode()
    except subprocess.CalledProcessError as e:
        logger.error(f"Traceroute command failed for {url}: {e.output.decode()}")
        return

    ips = [[ip for ip in line.split(' ') if valid_public_ip(ip)] for line in result.split('\n')]
    ips = [ip[0] for ip in ips if len(ip) > 0]

    ips[0] = get_public_ip()
    logger.info(f'IPs {ips}')

    geotrace = [resolve_ip(ip, cache_file_path) for ip in ips]
    logger.info(f'GeoTrace: {geotrace}')

    # --- NEW: Filter out unresolved IPs (where lat/lon is None) ---
    valid_points = [point for point in geotrace if point[1] is not None and point[2] is not None]

    if len(valid_points) < 2:
        logger.warning(f"Not enough geographic data to plot a path for {url}.")
        return

    ax = plt.axes(projection=ccrs.PlateCarree())
    ax.add_feature(cartopy.feature.LAND)
    ax.add_feature(cartopy.feature.OCEAN)
    ax.add_feature(cartopy.feature.COASTLINE,linewidth=0.3)
    ax.add_feature(cartopy.feature.BORDERS, linestyle=':',linewidth=0.3)
    ax.add_feature(cartopy.feature.LAKES, alpha=0.5)
    ax.add_feature(cartopy.feature.RIVERS)
    ax.set_global()

    # Generate the color gradient
    color_gradient = linear_gradient(start_hex='#0000FF',
    finish_hex="#FF0000", n=len(valid_points) - 1)

    # --- UPDATED: Plot lines using the filtered valid_points ---
    for i in range(len(valid_points) - 1):
        start = valid_points[i]
        stop = valid_points[i+1]

        # Plot the line segment
        plt.plot([start[2], stop[2]], [start[1], stop[1]],
        color=RGB_to_hex(color_gradient[i]),
        linewidth=2, transform=ccrs.Geodetic())

        # Plot the start marker
        plt.plot(start[2], start[1],
        color=RGB_to_hex(color_gradient[i]),
        marker='o', markersize=5, transform=ccrs.Geodetic())

    # Plot the very last marker
    last_point = valid_points[-1]
    plt.plot(last_point[2], last_point[1],
    color=RGB_to_hex(color_gradient[-1]),
    marker='o', markersize=5, transform=ccrs.Geodetic())

    # --- NEW: Add IP address labels for each point ---
    for point in valid_points:
        ip, lat, lon = point
        ax.text(lon + 0.15, lat + 0.15, ip,  # Offset text slightly
        transform=ccrs.Geodetic(),
        fontsize=7,fontweight='bold',
        ha='left',  # Horizontal alignment
        bbox=dict(facecolor='white', alpha=0.5, pad=0.1)) # Add white box for readability

    plt.title(f"Traceroute for {url}")
    plt.show()


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('urls', nargs='*')
    args = parser.parse_args()

    # Use XDG_CACHE_HOME for Flatpak compatibility
    cache_dir = pathlib.Path(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))) / 'geotraceroute'
    logger.info(f'CACHE DIR {cache_dir}')
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file_path = cache_dir / 'cache.json'
    if not cache_file_path.exists():
        with open(cache_file_path, 'w') as f:
            json.dump({}, f, indent=4)

    logger.debug(f'URLs {args.urls}')
    for url in args.urls:
        main(url, cache_file_path)
