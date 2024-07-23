import json
import logging
import re

from catalog.common import *
from catalog.models import *

_logger = logging.getLogger(__name__)


class BibliotekDKImageDownloader(BasicImageDownloader):
    def validate_response(self, response):

        # Fix broken content type on bibliotek.dk
        if response.headers.get("Content-Type") == "image/jpg":
            response.headers["Content-Type"] = "image/jpeg"

        # Fix broken content type on moreinfo.addi.dk
        if response.headers.get("Content-Type") == "image/JPEG":
            response.headers["Content-Type"] = "image/jpeg"

        return super().validate_response(response)


@SiteManager.register
class BibliotekDK(AbstractSite):
    SITE_NAME = SiteName.BibliotekDK
    ID_TYPE = IdType.BibliotekDK
    URL_PATTERNS = [
        r"https://bibliotek.dk/materiale/[^/]+/(work-of[^?/]+)",
    ]
    WIKI_PROPERTY_ID = ""
    DEFAULT_MODEL = Edition

    @classmethod
    def id_to_url(cls, id_value):
        return "https://bibliotek.dk/materiale/title/" + id_value

    def scrape(self):
        h = BasicDownloader(self.url, {"User-Agent": "curl/8.7.1"}).download().html()
        src = self.query_str(h, '//script[@id="__NEXT_DATA__"]/text()')
        if not src:
            raise ParseError(self, "__NEXT_DATA__ element")
        d = json.loads(src)["props"]["pageProps"]["initialData"]

        for key in list(d):
            m = re.search("query (\w+)", key)
            if m:
                d[m.group(1)] = d.pop(key)

        work = d["workJsonLd"]["data"]["work"]

        edition = work["manifestations"]["all"][0]

        title = work["titles"]["full"][0]
        description = work["abstract"][0]

        pub_year = edition["edition"]["publicationYear"]["display"]

        authors = []
        for creator in edition["creators"]:
            authors.append(creator["display"])

        isbn = None
        for id in edition["identifiers"]:
            if id["type"] == "ISBN":
                isbn = id["value"]

        language = "da"

        img_url = edition["cover"]["detail"]
        for e in work["manifestations"]["all"]:
            if e["cover"]["origin"] == "moreinfo":
                img_url = e["cover"]["detail"]
                break

        raw_img, ext = BibliotekDKImageDownloader.download_image(
            img_url, self.url, headers={"Accept": "*/*", "User-Agent": "curl/8.7.1"}
        )
        data = {
            "title": title,
            "localized_title": [{"lang": language, "text": title}],
            "author": authors,
            "language": language,
            "pub_year": pub_year,
            "isbn": isbn,
            "localized_description": (
                [{"lang": language, "text": description}] if description else []
            ),
            "cover_image_url": img_url,
        }

        return ResourceContent(
            metadata=data,
            cover_image=raw_img,
            cover_image_extention=ext,
            lookup_ids={IdType.ISBN: isbn},
        )
