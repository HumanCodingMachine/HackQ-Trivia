import asyncio
import logging
import operator
from html import unescape

import aiohttp
import bs4
import googleapiclient.discovery
import requests
from unidecode import unidecode

from hackq_trivia.config import config


class InvalidSearchServiceError(Exception):
    """Raise when search service specified in config is not recognized."""


class Searcher:
    HEADERS = {'User-Agent': 'HQbot'}
    BING_ENDPOINT = 'https://api.cognitive.microsoft.com/bing/v7.0/search'

    def __init__(self):
        self.timeout = config.getfloat('CONNECTION', 'Timeout')
        self.search_service = config.get('SEARCH', 'Service')

        bing_api_key = config.get('SEARCH', 'BingApiKey')
        self.bing_headers = {'Ocp-Apim-Subscription-Key': bing_api_key}

        self.google_cse_id = config.get('SEARCH', 'GoogleCseId')
        google_api_key = config.get('SEARCH', 'GoogleApiKey')
        self.google_service = googleapiclient.discovery.build('customsearch', 'v1', developerKey=google_api_key)

        if self.search_service == 'Bing':
            self.search_func = self.get_bing_links
        elif self.search_service == 'Google':
            self.search_func = self.get_google_links
        else:
            raise InvalidSearchServiceError(f'Search service type {self.search_service} was not recognized.')

        client_timeout = aiohttp.ClientTimeout(total=self.timeout)
        self.session = aiohttp.ClientSession(headers=Searcher.HEADERS, timeout=client_timeout)
        self.logger = logging.getLogger(__name__)

    async def fetch(self, url):
        try:
            async with self.session.get(url, timeout=self.timeout) as response:
                return await response.text()
        except asyncio.TimeoutError:
            self.logger.error(f'Server timeout to {url}')
        except Exception as e:
            self.logger.error(f'Server error to {url}')
            self.logger.error(e)

        return ""

    async def fetch_multiple(self, urls):
        tasks = [asyncio.create_task(self.fetch(url)) for url in urls]
        responses = await asyncio.gather(*tasks)
        return responses

    async def close(self):
        await self.session.close()

    def get_search_links(self, query, num_results):
        return self.search_func(query, num_results)

    def get_google_links(self, query, num_results):
        response = self.google_service.cse().list(q=query, cx=self.google_cse_id, num=num_results).execute()
        self.logger.debug(f'google: {query}, n={num_results}')
        self.logger.debug(response)
        return list(map(operator.itemgetter('link'), response['items']))

    def get_bing_links(self, query, num_results):
        # could be using aiohttp here...
        search_params = {'q': query, 'count': num_results}
        resp = requests.get(self.BING_ENDPOINT, headers=self.bing_headers, params=search_params)
        resp_data = resp.json()

        if resp.status_code != requests.codes.ok:
            logging.error(f'Bing search failed with status code {resp.status_code}')
            logging.error(resp_data)
            return []

        self.logger.debug(f'bing: {query}, n={num_results}')
        self.logger.debug(resp_data)

        return list(map(operator.itemgetter('url'), resp_data['webPages']['value']))

    @staticmethod
    def html_to_visible_text(html):
        soup = bs4.BeautifulSoup(html, features='html.parser')
        for s in soup(['style', 'script', '[document]', 'head', 'title']):
            s.extract()

        return unidecode(unescape(soup.get_text())).lower()
