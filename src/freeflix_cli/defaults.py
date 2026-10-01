# Default configurations acting as fallback
# These values are used if remote configuration cannot be loaded

DEFAULT_PLAYERS = {
    "wishonly": {
        "type": "default",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site;Content-Cache: no-cache",
        "mode": "proxy",
    },
    "hgbazooka": {"type": "default"},
    "hailindihg": {"type": "default"},
    "gradehgplus": {"type": "default"},
    "taylorplayer": {"type": "default"},
    "vidmoly": {"type": "vidmoly"},
    "tipfly": {"type": "default"},
    "ups2up": {"type": "default"},
    "ico3c": {"type": "default"},
    "fsvid": {"type": "fsvid", "referrer": "https://fsvid.lol"},
    "darkibox": {"type": "default"},
    "minochinos": {"type": "default"},
    "movearnpre": {
        "type": "default",
        "referrer": "full",
        "alt-used": False,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-origin",
    },
    "smoothpre": {
        "type": "default",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site;Content-Cache: no-cache",
        "mode": "proxy",
    },
    "vidhideplus": {"type": "default"},
    "dinisglows": {
        "type": "default",
        "referrer": "full",
        "alt-used": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-origin",
    },
    "mivalyo": {"type": "default"},
    "dingtezuni": {"type": "default"},
    "bingezove": {"type": "default"},
    "vidzy": {"type": "fsvid", "referrer": "https://vidzy.org"},
    # luluvid (french-manga). Rotating domain ; packed-JS like the
    # default extractor. May be unreachable when its domain rotates —
    # users fall back to vidzy in that case.
    "vidhsareup": {"type": "default"},
    "luluvid": {"type": "default"},
    "ok.ru": {"type": "default"},
    "videzz": {
        "type": "vidoza",
        "mode": "proxy",
        "no-header": True,
        "ext": "mp4",
    },
    "vidoza": {
        "type": "vidoza",
        "mode": "proxy",
        "no-header": True,
        "ext": "mp4",
    },
    "sendvid": {"type": "sendvid", "mode": "proxy", "ext": "mp4"},
    "sibnet": {
        "type": "sibnet",
        "mode": "proxy",
        "ext": "mp4",
        "referrer": "full",
        "no-header": True,
    },
    "uqload": {
        "type": "uqload",
        # uqload now serves a signed fsvid-family HLS (…/.urlset/master.m3u8)
        # that needs the embed's Origin (like the browser sends) — not the old
        # mp4. is-hls detection forces the /stream endpoint regardless of `ext`.
        "origin": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:same-site",
        "ext": "mp4",
    },
    "filemoon": {
        "type": "filemoon",
        "referrer": "https://ico3c.com/",
        "no-header": True,
    },
    "bysebuho": {
        "type": "filemoon",
        "referrer": "https://ico3c.com/",
        "no-header": True,
    },
    "bysekoze": {
        "type": "filemoon",
        "referrer": "https://ico3c.com/",
        "no-header": True,
    },
    "kakaflix": {"type": "kakaflix"},
    # ansembed.net — Anime-Sama's own embed (JWPlayer). The real stream is a
    # plain vmpx.online HLS (fsvid family, NOT Akamai), served only with the
    # embed's Origin+Referer. This is the player that actually works for recent
    # episodes (One Piece, Mushoku Tensei…) where embed4me now hits Akamai.
    "ansembed": {
        "type": "default",
        "referrer": "https://ansembed.net",
        "origin": True,
    },
    "embed4me": {
        "type": "embed4me",
        # embed4me now streams from external CDNs (e.g. TikTok) that hotlink-
        # check the browser's Origin + Sec-Fetch headers ; without them the CDN
        # 403s even with a valid Referer. Mirror the browser player's request.
        "origin": True,
        "sec_headers": "Sec-Fetch-Dest:empty;Sec-Fetch-Mode:cors;Sec-Fetch-Site:cross-site",
    },
    "coflix.upn": {"type": "embed4me"},
    "veev": {"type": "veev", "ext": "mp4"},
    "xtremestream": {"type": "xtremestream"},
    # french-stream's kokoflix.lol proxy : *_go.php?id=… 302-redirects to the
    # real mirror (playmogo/dood, luluvdo/voe, …) which is then dispatched
    # on its final host.
    "kokoflix": {"type": "kokoflix"},
    # DoodStream mirrors (playmogo.com…) : /e/ page + pass_md5 AJAX token.
    "playmogo": {"type": "dood", "ext": "mp4"},
    # Voe mirrors (luluvdo.com, lulust.com…) : word-substitution packed
    # JWPlayer setup. French-Anime's "luluvid" player rotates between them.
    "luluvdo": {"type": "voe"},
    "lulust": {"type": "voe"},

}

DEFAULT_NEW_URL = {
    "lulustream": "luluvdo",
    "vidoza.net": "videzz.net",
    "oneupload.to": "oneupload.net",
    "uqload.cx": "uqload.is",
    # Dinisglows Player
    "mivalyo": "dinisglows",
    "vidhideplus": "dinisglows",
    "dingtezuni": "dinisglows",
    # Vidmoly Player — live domain is .net ; .to is parked, .biz/.me are 404.
    "vidmoly.to": "vidmoly.net",
    "vidmoly.biz": "vidmoly.net",
    "vidmoly.me": "vidmoly.net",
}

DEFAULT_KAKAFLIX_PLAYERS = {
    "moon2": "ico3c",
    "viper": "ico3c",
}

DEFAULT_SOURCE_PORTAL = {
    "french-stream": "https://french-stream.one",
    "french-manga": "https://w16.french-manga.net",
    "anime-sama": "https://anime-sama.pw",
    "coflix": "https://coflix.cymru",

    "sudatchi": "https://sudatchi.com",
    "animetsu": "https://animetsu.live",
    "animetsu-api": "https://b.animetsu.live",
    "animetsu-proxy": "https://ani.metsu.site/proxy",
    "allanime-api": "https://api.allanime.day/api",
    "allanime-referer": "https://allmanga.to",
    "allanime-base": "https://allanime.day",
    "anizone": "https://anizone.to",
    "videasy": "https://api.videasy.net",
    "videasy-referer": "https://cineby.gd",
    "vidlink": "https://vidlink.pro",
    "hexa": "https://themoviedb.hexa.su",
    "hexa-referer": "https://hexa.su",
    "multi-decrypt": "https://enc-dec.app/api",
    "mapple": "https://mapple.uk",
    "xpass": "https://play.xpass.top",
}
