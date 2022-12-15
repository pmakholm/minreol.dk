"""
The Movie Database
"""

import re
from django.conf import settings
from catalog.common import *
from .douban import *
from catalog.movie.models import *
from catalog.tv.models import *
import logging


_logger = logging.getLogger(__name__)


def search_tmdb_by_imdb_id(imdb_id):
    tmdb_api_url = f"https://api.themoviedb.org/3/find/{imdb_id}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&external_source=imdb_id"
    res_data = BasicDownloader(tmdb_api_url).download().json()
    return res_data


def _copy_dict(s, key_map):
    d = {}
    for src, dst in key_map.items():
        d[dst if dst else src] = s.get(src)
    return d


genre_map = {
    'Sci-Fi & Fantasy': 'Sci-Fi',
    'War & Politics': 'War',
    '儿童': 'Kids',
    '冒险': 'Adventure',
    '剧情': 'Drama',
    '动作': 'Action',
    '动作冒险': 'Action',
    '动画': 'Animation',
    '历史': 'History',
    '喜剧': 'Comedy',
    '奇幻': 'Fantasy',
    '家庭': 'Family',
    '恐怖': 'Horror',
    '悬疑': 'Mystery',
    '惊悚': 'Thriller',
    '战争': 'War',
    '新闻': 'News',
    '爱情': 'Romance',
    '犯罪': 'Crime',
    '电视电影': 'TV Movie',
    '真人秀': 'Reality-TV',
    '科幻': 'Sci-Fi',
    '纪录': 'Documentary',
    '肥皂剧': 'Soap',
    '脱口秀': 'Talk-Show',
    '西部': 'Western',
    '音乐': 'Music',
}


@SiteManager.register
class TMDB_Movie(AbstractSite):
    ID_TYPE = IdType.TMDB_Movie
    URL_PATTERNS = [r'\w+://www.themoviedb.org/movie/(\d+)']
    WIKI_PROPERTY_ID = '?'
    DEFAULT_MODEL = Movie

    @classmethod
    def id_to_url(self, id_value):
        return f"https://www.themoviedb.org/movie/{id_value}"

    def scrape(self):
        is_series = False
        if is_series:
            api_url = f"https://api.themoviedb.org/3/tv/{self.id_value}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&append_to_response=external_ids,credits"
        else:
            api_url = f"https://api.themoviedb.org/3/movie/{self.id_value}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&append_to_response=external_ids,credits"

        res_data = BasicDownloader(api_url).download().json()

        if is_series:
            title = res_data['name']
            orig_title = res_data['original_name']
            year = int(res_data['first_air_date'].split(
                '-')[0]) if res_data['first_air_date'] else None
            imdb_code = res_data['external_ids']['imdb_id']
            showtime = [{res_data['first_air_date']: "首播日期"}
                        ] if res_data['first_air_date'] else None
            duration = None
        else:
            title = res_data['title']
            orig_title = res_data['original_title']
            year = int(res_data['release_date'].split('-')
                       [0]) if res_data['release_date'] else None
            showtime = [{res_data['release_date']: "发布日期"}
                        ] if res_data['release_date'] else None
            imdb_code = res_data['imdb_id']
            # in minutes
            duration = res_data['runtime'] if res_data['runtime'] else None

        genre = list(map(lambda x: genre_map[x['name']] if x['name']
                         in genre_map else 'Other', res_data['genres']))
        language = list(map(lambda x: x['name'], res_data['spoken_languages']))
        brief = res_data['overview']

        if is_series:
            director = list(map(lambda x: x['name'], res_data['created_by']))
        else:
            director = list(map(lambda x: x['name'], filter(
                lambda c: c['job'] == 'Director', res_data['credits']['crew'])))
        playwright = list(map(lambda x: x['name'], filter(
            lambda c: c['job'] == 'Screenplay', res_data['credits']['crew'])))
        actor = list(map(lambda x: x['name'], res_data['credits']['cast']))
        area = []

        other_info = {}
        # other_info['TMDB评分'] = res_data['vote_average']
        # other_info['分级'] = res_data['contentRating']
        # other_info['Metacritic评分'] = res_data['metacriticRating']
        # other_info['奖项'] = res_data['awards']
        # other_info['TMDB_ID'] = id
        if is_series:
            other_info['Seasons'] = res_data['number_of_seasons']
            other_info['Episodes'] = res_data['number_of_episodes']

        # TODO: use GET /configuration to get base url
        img_url = ('https://image.tmdb.org/t/p/original/' + res_data['poster_path']) if res_data['poster_path'] is not None else None

        pd = ResourceContent(metadata={
            'title': title,
            'orig_title': orig_title,
            'other_title': None,
            'imdb_code': imdb_code,
            'director': director,
            'playwright': playwright,
            'actor': actor,
            'genre': genre,
            'showtime': showtime,
            'site': None,
            'area': area,
            'language': language,
            'year': year,
            'duration': duration,
            'season': None,
            'episodes': None,
            'single_episode_length': None,
            'brief': brief,
            'cover_image_url': img_url,
        })
        if imdb_code:
            pd.lookup_ids[IdType.IMDB] = imdb_code
        if pd.metadata["cover_image_url"]:
            imgdl = BasicImageDownloader(pd.metadata["cover_image_url"], self.url)
            try:
                pd.cover_image = imgdl.download().content
                pd.cover_image_extention = imgdl.extention
            except Exception:
                _logger.debug(f'failed to download cover for {self.url} from {pd.metadata["cover_image_url"]}')
        return pd


@SiteManager.register
class TMDB_TV(AbstractSite):
    ID_TYPE = IdType.TMDB_TV
    URL_PATTERNS = [r'\w+://www.themoviedb.org/tv/(\d+)[^/]*$', r'\w+://www.themoviedb.org/tv/(\d+)[^/]*/seasons']
    WIKI_PROPERTY_ID = '?'
    DEFAULT_MODEL = TVShow

    @classmethod
    def id_to_url(self, id_value):
        return f"https://www.themoviedb.org/tv/{id_value}"

    def scrape(self):
        is_series = True
        if is_series:
            api_url = f"https://api.themoviedb.org/3/tv/{self.id_value}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&append_to_response=external_ids,credits"
        else:
            api_url = f"https://api.themoviedb.org/3/movie/{self.id_value}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&append_to_response=external_ids,credits"

        res_data = BasicDownloader(api_url).download().json()

        if is_series:
            title = res_data['name']
            orig_title = res_data['original_name']
            year = int(res_data['first_air_date'].split(
                '-')[0]) if res_data['first_air_date'] else None
            imdb_code = res_data['external_ids']['imdb_id']
            showtime = [{res_data['first_air_date']: "首播日期"}
                        ] if res_data['first_air_date'] else None
            duration = None
        else:
            title = res_data['title']
            orig_title = res_data['original_title']
            year = int(res_data['release_date'].split('-')
                       [0]) if res_data['release_date'] else None
            showtime = [{res_data['release_date']: "发布日期"}
                        ] if res_data['release_date'] else None
            imdb_code = res_data['imdb_id']
            # in minutes
            duration = res_data['runtime'] if res_data['runtime'] else None

        genre = list(map(lambda x: genre_map[x['name']] if x['name']
                         in genre_map else 'Other', res_data['genres']))
        language = list(map(lambda x: x['name'], res_data['spoken_languages']))
        brief = res_data['overview']

        if is_series:
            director = list(map(lambda x: x['name'], res_data['created_by']))
        else:
            director = list(map(lambda x: x['name'], filter(
                lambda c: c['job'] == 'Director', res_data['credits']['crew'])))
        playwright = list(map(lambda x: x['name'], filter(
            lambda c: c['job'] == 'Screenplay', res_data['credits']['crew'])))
        actor = list(map(lambda x: x['name'], res_data['credits']['cast']))
        area = []

        other_info = {}
        # other_info['TMDB评分'] = res_data['vote_average']
        # other_info['分级'] = res_data['contentRating']
        # other_info['Metacritic评分'] = res_data['metacriticRating']
        # other_info['奖项'] = res_data['awards']
        # other_info['TMDB_ID'] = id
        if is_series:
            other_info['Seasons'] = res_data['number_of_seasons']
            other_info['Episodes'] = res_data['number_of_episodes']

        # TODO: use GET /configuration to get base url
        img_url = ('https://image.tmdb.org/t/p/original/' + res_data['poster_path']) if res_data['poster_path'] is not None else None

        season_links = list(map(lambda s: {
            'model': 'TVSeason',
            'id_type': IdType.TMDB_TVSeason,
            'id_value': f'{self.id_value}-{s["season_number"]}',
            'title': s['name'],
            'url': f'{self.url}/season/{s["season_number"]}'}, res_data['seasons']))
        pd = ResourceContent(metadata={
            'title': title,
            'orig_title': orig_title,
            'other_title': None,
            'imdb_code': imdb_code,
            'director': director,
            'playwright': playwright,
            'actor': actor,
            'genre': genre,
            'showtime': showtime,
            'site': None,
            'area': area,
            'language': language,
            'year': year,
            'duration': duration,
            'season': None,
            'episodes': None,
            'single_episode_length': None,
            'brief': brief,
            'cover_image_url': img_url,
            'related_resources': season_links,
        })
        if imdb_code:
            pd.lookup_ids[IdType.IMDB] = imdb_code

        if pd.metadata["cover_image_url"]:
            imgdl = BasicImageDownloader(pd.metadata["cover_image_url"], self.url)
            try:
                pd.cover_image = imgdl.download().content
                pd.cover_image_extention = imgdl.extention
            except Exception:
                _logger.debug(f'failed to download cover for {self.url} from {pd.metadata["cover_image_url"]}')
        return pd


@SiteManager.register
class TMDB_TVSeason(AbstractSite):
    ID_TYPE = IdType.TMDB_TVSeason
    URL_PATTERNS = [r'\w+://www.themoviedb.org/tv/(\d+)[^/]*/season/(\d+)[^/]*$']
    WIKI_PROPERTY_ID = '?'
    DEFAULT_MODEL = TVSeason
    ID_PATTERN = r'^(\d+)-(\d+)$'

    @classmethod
    def url_to_id(cls, url: str):
        u = next(iter([re.match(p, url) for p in cls.URL_PATTERNS if re.match(p, url)]), None)
        return u[1] + '-' + u[2] if u else None

    @classmethod
    def id_to_url(cls, id_value):
        v = id_value.split('-')
        return f"https://www.themoviedb.org/tv/{v[0]}/season/{v[1]}"

    def scrape(self):
        v = self.id_value.split('-')
        api_url = f"https://api.themoviedb.org/3/tv/{v[0]}/season/{v[1]}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&append_to_response=external_ids,credits"
        d = BasicDownloader(api_url).download().json()
        if not d.get('id'):
            raise ParseError('id')
        pd = ResourceContent(metadata=_copy_dict(d, {'name': 'title', 'overview': 'brief', 'air_date': 'air_date', 'season_number': 0, 'external_ids': 0}))
        pd.metadata['required_resources'] = [{
            'model': 'TVShow',
            'id_type': IdType.TMDB_TV,
            'id_value': v[0],
            'title': f'TMDB TV Show {v[0]}',
            'url': f"https://www.themoviedb.org/tv/{v[0]}",
        }]
        pd.lookup_ids[IdType.IMDB] = d['external_ids'].get('imdb_id')
        pd.metadata['cover_image_url'] = ('https://image.tmdb.org/t/p/original/' + d['poster_path']) if d['poster_path'] else None
        pd.metadata['title'] = pd.metadata['title'] if pd.metadata['title'] else f'Season {d["season_number"]}'
        pd.metadata['episode_number_list'] = list(map(lambda ep: ep['episode_number'], d['episodes']))
        pd.metadata['episode_count'] = len(pd.metadata['episode_number_list'])
        if pd.metadata["cover_image_url"]:
            imgdl = BasicImageDownloader(pd.metadata["cover_image_url"], self.url)
            try:
                pd.cover_image = imgdl.download().content
                pd.cover_image_extention = imgdl.extention
            except Exception:
                _logger.debug(f'failed to download cover for {self.url} from {pd.metadata["cover_image_url"]}')

        # get external id from 1st episode
        if pd.lookup_ids[IdType.IMDB]:
            _logger.warning("Unexpected IMDB id for TMDB tv season")
        elif len(pd.metadata['episode_number_list']) == 0:
            _logger.warning("Unable to lookup IMDB id for TMDB tv season with zero episodes")
        else:
            ep = pd.metadata['episode_number_list'][0]
            api_url2 = f"https://api.themoviedb.org/3/tv/{v[0]}/season/{v[1]}/episode/{ep}?api_key={settings.TMDB_API3_KEY}&language=zh-CN&append_to_response=external_ids,credits"
            d2 = BasicDownloader(api_url2).download().json()
            if not d2.get('id'):
                raise ParseError('episode id for season')
            pd.lookup_ids[IdType.IMDB] = d2['external_ids'].get('imdb_id')
        return pd