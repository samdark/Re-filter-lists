import socket
import geoip2.database
import logging
import requests
import ipaddress
import time
from collections import defaultdict
from idna import encode as idna_encode

# Paths to input files
IP_LST_PATH = "ip.lst"
DOMAINS_LST_PATH = "domains.lst"
OUTPUT_FILE = "ipsum.lst"

# Path to the GeoLite2 ASN database
GEOIP_DB_PATH = "GeoLite2-ASN.mmdb"

# Initialize the GeoIP2 reader
reader = geoip2.database.Reader(GEOIP_DB_PATH)

# Set up logging
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s - %(levelname)s - %(message)s",
                    handlers=[
                        logging.FileHandler("summary.log", mode='a'),
                        logging.StreamHandler()
                    ])

# Trusted ASNs for company domains
COMPANY_DOMAINS = {
    'google.com': [15169],
    'youtube.com': [15169],
    'ggpht.com': [15169],
    'facebook.com': [32934],
    'instagram.com': [32934],
    'whatsapp.com': [32934],
    'fbcdn.net': [32934],
    'microsoft.com': [8075],
    'linkedin.com': [14492],
    'netflix.com': [2906],
    'akamai.com': [20940],
    'twitter.com': [13414],
    'x.com': [13414],
    'dropbox.com': [19679],
    'tesla.com': [394161]
}


# Function to summarize IPs into /28 subnets at most
def summarize_ips(ips):
    try:
        # Remove duplicates and sort IPs, treating them as networks (e.g., x.x.x.x/32)
        networks = [ipaddress.ip_network(ip, strict=False) for ip in set(ips)]
        collapsed_networks = ipaddress.collapse_addresses(networks)
        summarized_networks = []

        for network in collapsed_networks:
            if network.prefixlen < 28:  # If network is bigger than /28, split into /28
                for subnet in network.subnets(new_prefix=28):
                    summarized_networks.append(subnet)
            else:
                summarized_networks.append(network)

        logging.info(f"Summarized networks: {summarized_networks}")
        return summarized_networks
    except ValueError as e:
        logging.error(f"Error summarizing IPs: {e}")
        return []


# Function to handle rate-limiting errors (429) and retry after waiting
def handle_rate_limit():
    wait_time = 60  # Wait time of 60 seconds
    logging.warning(f"Rate limit hit. Waiting for {wait_time} seconds.")
    time.sleep(wait_time)


# Function to get CIDRs for a domain from ASN using GeoLite2
def get_cidr_for_asn(asn):
    try:
        url = f"https://api.bgpview.io/asn/{asn}/prefixes"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            return [prefix['prefix'] for prefix in data['data']['ipv4_prefixes']]

        elif response.status_code == 429:
            handle_rate_limit()
            return get_cidr_for_asn(asn)  # Retry after waiting

        elif response.status_code == 403:
            logging.error(f"Access forbidden for ASN {asn}, skipping.")
            return []

        return []
    except Exception as e:
        logging.error(f"Error retrieving CIDRs for ASN {asn}: {e}")
        return []


# Function to resolve a domain with retries and punycode support
def resolve_domain(domain):
    try:
        domain_punycode = idna_encode(domain).decode('utf-8')
        return socket.gethostbyname_ex(domain_punycode)[2]
    except Exception as e:
        logging.error(f"Could not resolve domain {domain}: {e}")
        return []


# Function to check if a domain matches COMPANY_DOMAINS and fetch CIDRs
def process_domain_for_asn(domain):
    asns = COMPANY_DOMAINS.get(domain, [])
    cidrs = set()
    if asns:
        for asn in asns:
            cidrs.update(get_cidr_for_asn(asn))
    return cidrs


# Function to read IPs from ip.lst
def read_ips_from_file(file_path):
    try:
        with open(file_path, 'r') as f:
            return [line.strip() for line in f.readlines() if line.strip()]
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        return []


# Function to write summarized CIDRs to ipsum.lst
def write_summarized_ips(ips, filename):
    try:
        with open(filename, 'w') as f:
            for cidr in ips:
                f.write(f"{cidr}\n")
        logging.info(f"Written summarized IPs to {filename}")
    except Exception as e:
        logging.error(f"Error writing summarized IPs to file: {e}")


# Main function to process ip.lst, summarize, and add CIDRs for company domains
def main():
    # Read IPs from ip.lst
    ips = read_ips_from_file(IP_LST_PATH)

    # Summarize the IPs into /28 networks
    summarized_ips = summarize_ips(ips)

    # Check domains.lst for COMPANY_DOMAINS matches and get corresponding CIDRs
    domains = read_ips_from_file(DOMAINS_LST_PATH)
    company_cidrs = set()

    for domain in domains:
        company_cidrs.update(process_domain_for_asn(domain))

    # Combine summarized IPs and company CIDRs
    final_cidrs = set(summarized_ips) | company_cidrs

    # Write the final output to ipsum.lst
    write_summarized_ips(final_cidrs, OUTPUT_FILE)


if __name__ == "__main__":
    main()
