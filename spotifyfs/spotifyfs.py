#!/usr/bin/python
# -*- coding: utf-8 -*-

from stat import S_IFDIR, S_IFLNK, S_IFREG

from typing import Tuple, Callable, Iterator, Union, Any, Iterable, Dict

import spotipy.util

from expiringdict import ExpiringDict
from functools import partial
from stat import S_IFDIR, S_IFLNK, S_IFREG

import asyncio
import aiohttp
import urllib
import inspect
import sys
import json
import errno

import fuse
import fusetree
import logging
import audio_fetch

FILE_MODE = S_IFREG | 0o444
FILE_MODE_RW = S_IFREG | 0o666
DIR_MODE = S_IFDIR | 0o555
DIR_MODE_RW = S_IFDIR | 0o777

SPOTIFY_CLIENT_ID='85fe52cff756410095a3714c028c288b'
SPOTIFY_CLIENT_SECRET='822d085d81af4aae9ad800609dcc3706'

def escape_filename(name):
    return name.replace('/', '∕')

class SpotifyFS(fusetree.DictDir):
    def __init__(self, country='us'):
        # There is a massive performance gain if we cache a directory's contents.
        self.cache = ExpiringDict(max_len=64*1024, max_age_seconds=3600)
        self.country = country

        #FIXME -- Don't rely on spotipy and copy-pasting for authentication
        self.token = spotipy.util.prompt_for_user_token(
            '1252589511',
            'user-library-read user-library-modify user-follow-read user-follow-modify playlist-read-private playlist-read-collaborative playlist-modify-private',
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri='https://example.com')

        self.artistNodes = {}
        self.albumNodes = {}
        self.trackNodes = {}
        self.playlistNodes = {}

        fusetree.DictDir.__init__(self, {
            'Artists': FollowedArtistsNode(self, id=None, mode=DIR_MODE_RW),
            #'Playlists': UserPlaylistsNode(self, id='me', mode=DIR_MODE_RW),
            #'Saved Albums': {},
            #'Saved Tracks': {},
            # Top Artists
            # Top Tracks
            #'Recently Played': {},
            #'Categories': {},
            #'Featured Playlists': {},
            #'New Releases': {},
            #'Recommendations': {},
        })

    async def remember(self):
        self.aiohttp_session = aiohttp.ClientSession(loop=asyncio.get_event_loop())
        self.audio_fetch = audio_fetch.SpotifyAudioFetcher(loop=asyncio.get_event_loop())

    async def forget(self) -> None:
        await self.aiohttp_session.close()

    async def request(self, url, method='GET', **kwargs):
        url = urllib.parse.urljoin('https://api.spotify.com/v1/', url)
        response = await self.aiohttp_session.request(url=url, headers={'Authorization': f'Bearer {self.token}'}, method=method, **kwargs)
        return await response.json()

    async def request_list(self, path, key=None, **kwargs):
        it = await self.request(path, **kwargs)
        if key is not None:
            it = it[key]
        items = it['items']
        while it['next']:
            it = await self.request(it['next'])
            if key is not None:
                it = it[key]
            items += it['items']
        return items

    def getArtist(self, id):
        try:
            return self.artistNodes[id]
        except:
            artistNode = ArtistNode(self, id, DIR_MODE)
            self.artistNodes[id] = artistNode
            return artistNode

    def getAlbum(self, id):
        try:
            return self.albumNodes[id]
        except:
            albumNode = AlbumNode(self, id, DIR_MODE)
            self.albumNodes[id] = albumNode
            return albumNode

    def getPlaylist(self, userId, playlistId):
        try:
            return self.playlistNodes[(userId, playlistId)]
        except:
            playlistNode = ""#PlaylistNode(self, (userId, playlistId), DIR_MODE_RW)
            self.playlistNodes[(userId, playlistId)] = playlistNode
            return playlistNode

    def getTrack(self, id, duration_ms):
        try:
            return self.trackNodes[id]
        except:
            trackNode = TrackNode(self, id, FILE_MODE, duration_ms)
            self.trackNodes[id] = trackNode
            return trackNode

class SpotifyNode(fusetree.Node):
    def __init__(self, spotifyfs, id, mode):
        self.mode = mode
        self.spotifyfs = spotifyfs
        self.id = id
        self.cache_id = (self.__class__.__name__, id)

    async def getattr(self) -> fusetree.Stat:
        return fusetree.Stat(
            st_mode=self.mode
        )

    async def invalidate(self):
        del self.spotifyfs.cache[self.cache_id]


class SpotifyDir(SpotifyNode):
    content_file: str = None
    image_file: str = None
    default_image = None

    def __init__(self, spotifyfs, id, mode):
        super().__init__(spotifyfs, id, mode)

        self._raw_content = None
        self._files = None

    async def invalidate(self):
        super().invalidate()
        self._raw_content = None
        self._files = None

    async def fetch_content(self):
        """
        Fetches all relevant data for this node from Spotify
        """
        return {}  ## Override this method!

    async def describe_content(self, content) -> Dict[str, str]:
        """
        Returns a label, URL and image URL that describe this folder
        """
        ret = {}
        for key in ['name', 'url', 'uri']:
            try:
                ret[key] = content[key]
            except:
                pass

        try:
            ret['image'] = content['images'][0]['url']
        except:
            pass

        return ret

    async def content_to_files(self, content) -> Dict[str, fusetree.Node]:
        """
        List the content of this directory
        """
        return {} ## Override this to fetch something

    async def content(self):
        """
        Fetches all relevant data for this node, as fetched from Spotify.

        Caching will be used for speed, call invalidate() if you expect something to change.
        """
        if self._raw_content is None:
            self._raw_content = self.spotifyfs.cache.get(self.cache_id, None)
            if self._raw_content is None:
                self._raw_content = await self.fetch_content()
                self.spotifyfs.cache[self.cache_id] = self._raw_content
        return self._raw_content

    async def files(self) -> Dict[str, fusetree.Node]:
        if self._files is None:
            content = await self.content()
            content_desc = await self.describe_content(content)

            files = {}
            files['.directory'] = inspect.cleandoc(f"""
                [Desktop Entry]
                Name={content_desc.get('name', '')}
                Comment={content_desc.get('url', '')}
                Icon=./{self.image_file}
                Type=Directory
                """)

            if self.content_file is not None:
                files[self.content_file] = json.dumps(content, indent=4)

            if self.image_file is not None:
                image_url = content_desc.get('image', self.default_image)
                if image_url is not None:
                    files[self.image_file] = fusetree.HttpFile(image_url)

            content_files = await self.content_to_files(content)
            files.update({
                escape_filename(name): node
                for name, node in content_files.items()
            })

            self._files = files
        return self._files

    async def opendir(self):
        return list((await self.files()).items())

    async def lookup(self, name: str):
        files = await self.files()
        return files.get(name, None)

    #async def add_child(self, name: str, node: fusetree.Node = None) -> None:
        #raise fuse.FuseOSError(errno.ENOSYS)

    #async def mkdir(self, path: fusetree.Path, name: str, mode: int) -> None:
        #await self.add_child(name)

    #async def mknod(self, path: fusetree.Path, name: str, mode: int, dev: int) -> None:
        #await self.add_child(name)

    #async def link(self, path: fusetree.Path, name: str, target: fusetree.Path) -> None:
        #await self.add_child(name, target)



    #async def remove_child(self, name: str) -> None:
        #raise fuse.FuseOSError(errno.ENOSYS)

    #def unlink(self, name: str) -> None:
        #await self.remove_child(name)

    #def rmdir(self, name: str) -> None:
        #self._remove_from_parent(path)


    #def remove_child(self, name: str, node: fusetree.Node) -> None:
        #raise fuse.FuseOSError(errno.ENOSYS)

    #def rename_child(self, old_name: str, new_name: str, node: fusetree.Node) -> None:
        #raise fuse.FuseOSError(errno.ENOSYS)

    #def get_hidden_file(self, name: str) -> LazyNode:
        #"""
        #Fetch something that has not been listed on the directory.
        #E.g., accessing `Artists/Random Dude` should work whenever
        #Random Dude is in your favorite list or not
        #"""
        #return None

    #def invalidate_cache(self) -> None:
        #"""
        #Remove all cached content relative to this node
        #"""
        #del self.cache[self.cache_id]
        #self.cached_entries = None

    #@property
    #def content(self) -> NodeContent:
        #"""
        #Fetches all relevant data for this node, as fetched from Spotify.

        #Caching will be used for speed, call invalidate() if you expect something to change.
        #"""
        #content = self.cache.get(self.cache_id, None)
        #if content is None:
            #content = self.fetch_content()
            #self.cache[self.cache_id] = content

        #return content

    #def opendir(self, path: fusetree.Path) -> Iterator[Tuple[str, fusetree.Stat]]:
        #content = self.content
        #self.cached_entries = {}

        #yield '.directory', FILE_MODE
        #if self.content_file is not None:
            #yield self.content_file, FILE_MODE
        #if self.image_file is not None:
            #try:
                #url = self.content['images'][0]['url']
                #yield self.image_file, FILE_MODE
            #except:
                #pass

        #for name, entry, stat in self.list_files(content):
            #self.cached_entries[name] = entry
            #yield name, stat


    #def __getitem__(self, name) -> fusetree.Node_Like:
        #if name == '.directory':
            #return inspect.cleandoc(f"""
                #[Desktop Entry]
                #Name=Foo
                #Comment=Foobar comment
                #Icon=./{self.image_file}
                #Type=Directory
                #""")

        #if name == self.content_file:
            #return json.dumps(self.content, indent=4)

        #if name == self.image_file:
            #try:
                #return fusetree.UrllibFile(self.content['images'][0]['url'])
            #except:
                #return fusetree.UrllibFile(self.default_image)


        #if self.cached_entries is None:
            #list(self.opendir(None))

        #handler = self.cached_entries.get(name, None)
        #if handler is None:
            #handler = self.get_hidden_file(name)
            #if handler is not None:
                #self.cached_entries[name] = handler

        #if callable(handler):
            #handler = handler()
        #return handler


class ArtistNode(SpotifyDir):
    content_file = '.artist.json'
    image_file = '.artist.jpg'

    async def fetch_content(self):
        content, related_artists, top_tracks, albuns = await asyncio.gather(
            self.spotifyfs.request(f'artists/{self.id}'),
            self.spotifyfs.request(f'artists/{self.id}/related-artists'),
            self.spotifyfs.request(f'artists/{self.id}/top-tracks', params={'country': self.spotifyfs.country}),
            self.spotifyfs.request_list(f'artists/{self.id}/albums', params={'market': self.spotifyfs.country, 'limit': 50}),
        )
        content['related-artists'] = related_artists['artists']
        content['top-tracks'] = top_tracks['tracks']
        content['albuns'] = albuns
        return content

    async def content_to_files(self, content):
        return {
            'Related Artists': {
                artist["name"]: self.spotifyfs.getArtist(artist['id'])
                for artist in content['related-artists']
            },
            'Top Tracks': {
                f'{track["name"]}.mp3': self.spotifyfs.getTrack(track['id'], track['duration_ms'])
                for i, track in enumerate(content['top-tracks'])
            },
            'Albuns': {
                album["name"]: self.spotifyfs.getAlbum(album['id'])
                for album in content['albuns']
            },
        }

class AlbumNode(SpotifyDir):
    content_file = '.album.json'
    image_file = '.album.jpg'

    async def fetch_content(self):
        album, tracks = await asyncio.gather(
            self.spotifyfs.request(f'albums/{self.id}'),
            self.spotifyfs.request_list(f'albums/{self.id}/tracks'),
        )
        album['tracks'] = tracks
        return album

    async def content_to_files(self, content):
        tracks = content['tracks']

        track_numbers = set()
        disc_numbers = set()

        for track in tracks:
            track_numbers.add(track['track_number'])
            disc_numbers.add(track['disc_number'])
        track_digits = len(str(max(track_numbers)))
        disc_digits = len(str(max(disc_numbers)))

        ret = {}
        for track in tracks:
            filename = track['name'] + '.mp3'
            track_number = str(track['track_number']).zfill(track_digits)
            disc_number = str(track['disc_number']).zfill(disc_digits)

            if len(disc_numbers) > 1:
                filename = f'{disc_number}:{track_number} - {filename}'
            elif len(track_numbers) > 1:
                filename = f'{track_number} - {filename}'

            ret[filename] = self.spotifyfs.getTrack(track['id'], track['duration_ms'])
        return ret


class FollowedArtistsNode(SpotifyDir):
    content_file = '.followed_artists.json'

    async def fetch_content(self):
        return await self.spotifyfs.request_list(f'me/following', params={'type': 'artist', 'limit': 50}, key='artists')

    async def content_to_files(self, content):
        return {
            artist["name"]: self.spotifyfs.getArtist(artist['id'])
            for artist in content
        }


class TrackNode(SpotifyNode):
    content_file = '.track.json'

    def __init__(self, spotifyfs, id, mode, duration_ms, bitrate=256):
            super().__init__(spotifyfs, id, mode)
            self.bitrate = bitrate
            self.duration_ms = duration_ms
            self.shared_handle = None

    async def getattr(self) -> fusetree.Stat:
        id3_v1_size = 128  # Fix size ID3v1
        id3_v2_size = 4096  # Wild guess -- Depends mostly on cover image
        audio_size = self.duration_ms * self.bitrate // 8

        #if self.shared_handle is not None:
            #if self.shared_handle.id3v1 is not None:
                #id3_v1_size = len(self.shared_handle.id3v1)
            #if self.shared_handle.id3v2 is not None:
                #id3_v2_size = len(self.shared_handle.id3v2)
            #if self.shared_handle.playback is not None:
                #if self.shared_handle.playback.finished and self.shared_handle.playback.error is None:
                    #audio_size = len(self.shared_handle.playback.buf)
                #else:
                    #audio_size = max(audio_size, len(self.shared_handle.playback.buf))

        return fusetree.Stat(
            st_mode = self.mode,
            st_size = id3_v1_size + id3_v2_size + audio_size
        )

    async def open(self, mode):
        if self.shared_handle is None:
            self.shared_handle = TrackNode.Handle(self)
        self.shared_handle.refs += 1
        return self.shared_handle

    class Handle (fusetree.FileHandle):
        def __init__(self, node):
            super().__init__(node, direct_io=True)
            self.playback = None
            self.id3v1 = None
            self.id3v2 = None
            self.refs = 0

        async def read(self, size: int, offset: int) -> bytes:
            if self.id3v2 is None:
                track = await self.node.spotifyfs.request(f'tracks/{self.node.id}')
                album = await self.node.spotifyfs.getAlbum(track['album']['id']).content()
                self.id3v1, self.id3v2 = await self.id3(track, album)
                print('ID3v2 len=', len(self.id3v2))
            ret = self.id3v2[offset:offset+size]
            if len(ret) != 0:
                return ret
            else:
                offset -= len(self.id3v2)


            if self.playback is None:
                self.playback = self.node.spotifyfs.audio_fetch.play(
                        self.node.id,
                        lame_args = dict(
                            bitrate = self.node.bitrate,
                            write_id3tag_automatic = False
                        ))
            ret = await self.playback.read(offset, size)
            if len(ret) != 0:
                return ret
            else:
                offset -= len(self.playback.buf)


            return self.id3v1[offset:offset+size]

        async def release(self) -> None:
            self.refs -= 1
            if self.refs == 0:
                self.node.shared_handle = None

                if self.playback is not None:
                    await self.playback.close()

        async def id3(self, track, album):
            """
            Generate an ID3 frame to be prepended to actual MP3 stream
            Inspired by spotify-downloader:
            https://github.com/ritiek/spotify-downloader/blob/master/core/metadata.py
            """
            from mutagen.easyid3 import EasyID3
            from mutagen.id3 import ID3, TORY, TYER, TPUB, APIC, USLT, COMM
            import tempfile

            with tempfile.TemporaryFile() as fp:
                num_discs = 0
                num_tracks = 0
                for t in album['tracks']:
                    num_discs = max(num_discs, t['disc_number'])
                    if t['disc_number'] == track['disc_number']:
                        num_tracks = max(num_tracks, t['track_number'])

                metadata = EasyID3()
                metadata['website'] = track['external_urls']['spotify']
                metadata['title'] = track['name']
                metadata['artist'] = [artist['name'] for artist in track['artists']]
                metadata['album'] = album['name']
                metadata['albumartist'] = [artist['name'] for artist in album['artists']]
                metadata['tracknumber'] = [track['track_number'], num_tracks]
                metadata['discnumber'] = [track['disc_number'], num_discs]
                metadata['length'] = str(track['duration_ms'] / 1000.0)
                metadata['date'] = album['release_date']
                metadata['genre'] = album['genres']

                try:
                    metadata['encodedby'] = album['label']
                except:
                    pass

                try:
                    metadata['copyright'] = album['copyrights'][0]['text']
                except:
                    pass

                try:
                    metadata['isrc'] = track['external_ids']['isrc']
                except:
                    pass

                metadata.save(fp, v1=2)
                fp.seek(0)

                metadata = ID3(fp)
                try:
                    img_url = track['album']['images'][0]['url']
                    async with self.node.spotifyfs.aiohttp_session.request(url=img_url, method='GET') as response:
                        albumart = await response.read()
                        metadata['APIC'] = APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=albumart)
                except:
                    import traceback
                    traceback.print_exc()
                    pass

                ##try to fetch lyrics -- This can be improved...
                #try:
                    #import lyricwikia
                    #print('Looking for lyrics', track['artists'][0]['name'], track['name'])
                    #lyrics = lyricwikia.get_lyrics(track['artists'][0]['name'], track['name'])
                    #metadata['USLT'] = USLT(encoding=3, desc=u'Lyrics', text=lyrics)
                #except:
                    #print('lyrics lookup failed')
                    #pass

                metadata.save(fp)
                fp.seek(0)

                return b'', fp.read()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    fusetree.FuseTree(SpotifyFS(), sys.argv[1], foreground=True)
