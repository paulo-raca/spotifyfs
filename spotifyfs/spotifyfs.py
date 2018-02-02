#!/usr/bin/python
# -*- coding: utf-8 -*-

from stat import S_IFDIR, S_IFLNK, S_IFREG

from typing import Tuple, Callable, Iterator, Union, Any

import spotipy
import spotipy.oauth2
import spotipy.util

from expiringdict import ExpiringDict
from functools import partial
from stat import S_IFDIR, S_IFLNK, S_IFREG

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
DIR_MODE = S_IFDIR | 0o444
DIR_MODE_RW = S_IFDIR | 0o666

class SpotifyFS(fusetree.DictDir):
    def __init__(self):
        # There is a massive performance gain if we cache a directory's contents.
        self.cache = ExpiringDict(max_len=64*1024, max_age_seconds=3600)

        self.token = spotipy.util.prompt_for_user_token(
            '1252589511',
            'user-library-read user-library-modify user-follow-read user-follow-modify playlist-read-private playlist-read-collaborative playlist-modify-private',
            client_id='85fe52cff756410095a3714c028c288b',
            client_secret='822d085d81af4aae9ad800609dcc3706',
            redirect_uri='https://example.com')
        self.spotify = spotipy.Spotify(auth=self.token)

        self.audio_fetch = audio_fetch.SpotifyAudioFetcher()

        self.artistNodes = {}
        self.albumNodes = {}
        self.trackNodes = {}
        self.playlistNodes = {}

        rootNode = {
            'Artists': FollowedArtistsNode(self, id=None, mode=DIR_MODE_RW),
            'Playlists': UserPlaylistsNode(self, id='me', mode=DIR_MODE_RW),
            #'Saved Albums': {},
            #'Saved Tracks': {},
            # Top Artists
            # Top Tracks
            #'Recently Played': {},
            #'Categories': {},
            #'Featured Playlists': {},
            #'New Releases': {},
            #'Recommendations': {},
        }

        fusetree.DictDir.__init__(self, rootNode)

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
            playlistNode = PlaylistNode(self, (userId, playlistId), DIR_MODE_RW)
            self.playlistNodes[(userId, playlistId)] = playlistNode
            return playlistNode

    def getTrack(self, id):
        try:
            return self.trackNodes[id]['audio.mp3']
        except:
            trackNode = TrackNode(self, id, DIR_MODE)
            self.trackNodes[id] = trackNode
            return trackNode['audio.mp3']


NodeContent = Any
LazyNode = Union[fusetree.Node_Like, Callable[[], fusetree.Node_Like]]


class SpotifyNode(fusetree.Node):
    def __init__(self, spotifyfs, id, mode):
        self.mode = mode
        self.spotifyfs = spotifyfs
        self.cache = spotifyfs.cache
        self.id = id
        self.cache_id = (self.__class__.__name__, id)
        self.cached_entries = None

    def getattr(self, path: fusetree.Path) -> fusetree.Stat:
        return fusetree.Stat(
            st_mode=self.mode
        )

    def _remove_from_parent(self, path: fusetree.Path) -> None:
        """
        Remove a file
        """
        parent_dir = path.elements[-2][1]

        if not isinstance(parent_dir, SpotifyDir):
            raise fuse.FuseOSError(errno.ENOSYS)

        parent_dir.remove_child(path.elements[-1][0], path.elements[-1][1])

    def unlink(self, path: fusetree.Path) -> None:
        self._remove_from_parent(path)

    def rmdir(self, path: fusetree.Path) -> None:
        self._remove_from_parent(path)

    def rename(self, path: fusetree.Path, new_path: fusetree.Path, new_name: str) -> None:
        src_dir = path.elements[-2][1]
        dest_dir = new_path.elements[-1][1]

        if src_dir != dest_dir or not isinstance(src_dir, SpotifyNode):
            raise fuse.FuseOSError(errno.EPERM)

        src_dir.rename_child(path.elements[-1][0], new_name, path.elements[-1][1])


class SpotifyDir(SpotifyNode, fusetree.BaseDir):
    content_file: str = None
    image_file: str = None
    default_image = 'https://www1-lw.xda-cdn.com/files/2013/09/music.jpg'

    def fetch_content(self) -> NodeContent:
        """
        Fetches all relevant data for this node from Spotify
        """
        return {}  ## Override this method!

    def list_files(self, content: NodeContent) -> Iterator[Tuple[str, LazyNode, fusetree.Stat]]:
        """
        List the content of this directory
        """
        return iter([])  ## Override this to fetch some

    def add_child(self, name_or_node: Union[str, fusetree.Node]) -> None:
        raise fuse.FuseOSError(errno.ENOSYS)

    def remove_child(self, name: str, node: fusetree.Node) -> None:
        raise fuse.FuseOSError(errno.ENOSYS)

    def rename_child(self, old_name: str, new_name: str, node: fusetree.Node) -> None:
        raise fuse.FuseOSError(errno.ENOSYS)

    def get_hidden_file(self, name: str) -> LazyNode:
        """
        Fetch something that has not been listed on the directory.
        E.g., accessing `Artists/Random Dude` should work whenever
        Random Dude is in your favorite list or not
        """
        return None

    def invalidate_cache(self) -> None:
        """
        Remove all cached content relative to this node
        """
        del self.cache[self.cache_id]
        self.cached_entries = None

    @property
    def content(self) -> NodeContent:
        """
        Fetches all relevant data for this node, as fetched from Spotify.

        Caching will be used for speed, call invalidate() if you expect something to change.
        """
        content = self.cache.get(self.cache_id, None)
        if content is None:
            content = self.fetch_content()
            self.cache[self.cache_id] = content

        return content

    def opendir(self, path: fusetree.Path) -> Iterator[Tuple[str, fusetree.Stat]]:
        content = self.content
        self.cached_entries = {}

        yield '.directory', FILE_MODE
        if self.content_file is not None:
            yield self.content_file, FILE_MODE
        if self.image_file is not None:
            try:
                url = self.content['images'][0]['url']
                yield self.image_file, FILE_MODE
            except:
                pass

        for name, entry, stat in self.list_files(content):
            self.cached_entries[name] = entry
            yield name, stat

    def mkdir(self, path: fusetree.Path, name: str, mode: int) -> None:
        self.add_child(name)

    def mknod(self, path: fusetree.Path, name: str, mode: int, dev: int) -> None:
        self.add_child(name)

    def link(self, path: fusetree.Path, name: str, target: fusetree.Path) -> None:
        self.add_child(target.target_node)

    def __getitem__(self, name) -> fusetree.Node_Like:
        if name == '.directory':
            return inspect.cleandoc(f"""
                [Desktop Entry]
                Name=Foo
                Comment=Foobar comment
                Icon=./{self.image_file}
                Type=Directory
                """)

        if name == self.content_file:
            return json.dumps(self.content, indent=4)

        if name == self.image_file:
            try:
                return fusetree.UrllibFile(self.content['images'][0]['url'])
            except:
                return fusetree.UrllibFile(self.default_image)


        if self.cached_entries is None:
            list(self.opendir(None))

        handler = self.cached_entries.get(name, None)
        if handler is None:
            handler = self.get_hidden_file(name)
            if handler is not None:
                self.cached_entries[name] = handler

        if callable(handler):
            handler = handler()
        return handler


class ArtistNode(SpotifyDir):
    # TODO:
    # - Related Artists
    # - Top Tracks

    content_file = '.artist.json'
    image_file = '.artist.jpg'

    def fetch_content(self) -> NodeContent:
        artist = self.spotifyfs.spotify.artist(self.id)

        albums_it = self.spotifyfs.spotify.artist_albums(self.id, limit=50)
        artist['albums'] = albums_it['items']
        while albums_it['next']:
            albums_it = self.spotifyfs.spotify.next(albums_it)
            artist['albums'] += albums_it['items']

        return artist

    def list_files(self, content: NodeContent) -> Iterator[Tuple[str, LazyNode, int]]:
        for album in content['albums']:
            filename = album['name']
            yield filename, partial(lambda id: self.spotifyfs.getAlbum(id), album['id']), DIR_MODE


class AlbumNode(SpotifyDir):
    content_file = '.album.json'
    image_file = '.album.jpg'

    def fetch_content(self) -> NodeContent:
        album = self.spotifyfs.spotify.album(self.id)

        tracks_it = album['tracks']
        album['tracks'] = tracks_it['items']
        while tracks_it['next']:
            tracks_it = self.spotifyfs.spotify.next(tracks_it)
            album['tracks'] += tracks_it['items']

        for track in album['tracks']:
            self.spotifyfs.cache[(TrackNode.__name__, track['id'])] = track

        return album

    def list_files(self, content: NodeContent) -> Iterator[Tuple[str, LazyNode, int]]:
        tracks = self.content['tracks']

        track_numbers = set()
        disc_numbers = set()

        for track in tracks:
            track_numbers.add(track['track_number'])
            disc_numbers.add(track['disc_number'])

        for track in tracks:
            filename = track['name'] + '.mp3'
            track_number = track['track_number']
            disc_number = track['disc_number']

            if len(track_numbers) > 1:
                filename = f'{track_number:03d} - {filename}'
                if len(disc_numbers) > 1:
                    filename = f'{disc_number:01d}:{filename}'

            yield filename, partial(lambda id: self.spotifyfs.getTrack(id), track['id']), FILE_MODE


class PlaylistNode(SpotifyDir):
    # TODO:
    # - Better parsing of track order from filename

    content_file = '.playlist.json'
    image_file = '.playlist.jpg'

    def fetch_content(self) -> NodeContent:
        playlist = self.spotifyfs.spotify.user_playlist(self.id[0], self.id[1])

        tracks_it = playlist['tracks']
        playlist['tracks'] = tracks_it['items']
        while tracks_it['next']:
            tracks_it = self.spotifyfs.spotify.next(tracks_it)
            playlist['tracks'] += tracks_it['items']

        playlist['tracks'] = [
            track['track']
            for track in playlist['tracks']
            if not track['is_local']
        ]

        for track in playlist['tracks']:
            self.spotifyfs.cache[(TrackNode.__name__, track['id'])] = track

        return playlist

    def list_files(self, content: NodeContent) -> Iterator[Tuple[str, LazyNode, int]]:
        n = 0
        for track in content['tracks']:
            filename = track['name'] + '.mp3'
            artist_names = ', '.join([artist['name'] for artist in track['artists']])
            if artist_names:
                filename = f'{artist_names} - {filename}'

            n += 1
            filename = f'{n:03d} - {filename}'
            yield filename, partial(lambda id: self.spotifyfs.getTrack(id), track['id']), FILE_MODE

    def add_child(self, name_or_node):
        track_id = None
        if isinstance(name_or_node, TrackNode) or isinstance(name_or_node, TrackAudioFile):
              track_id = name_or_node.id
        elif isinstance(name_or_node, str):
            results = self.spotifyfs.spotify.search(q=name_or_node, type='track')
            items = results['tracks']['items']
            if len(items) != 0:
                track_id = items[0]['id']

        print(f'Playlist.add_child {name_or_node}')
        if track_id is None:
            raise fuse.FuseOSError(errno.ENOENT)

        try:
            self.spotifyfs.spotify.user_playlist_add_tracks(self.id[0], self.id[1], [track_id])
            self.invalidate_cache()
        except:
            raise fuse.FuseOSError(errno.EPERM)

    def remove_child(self, name, node):
        track_id = None
        if isinstance(node, TrackNode) or isinstance(node, TrackAudioFile):
            track_id = node.id

        if track_id is None:
            raise fuse.FuseOSError(errno.ENOENT)

        try:
            position = int(name.split(' - ')[0]) - 1
            print(f'Removing {track_id} at {position}')

            self.spotifyfs.spotify.user_playlist_remove_specific_occurrences_of_tracks(
                self.id[0], self.id[1],
                [{'uri': track_id, 'positions':[position]}],
                snapshot_id=self.content['snapshot_id']
            )
            self.invalidate_cache()
        except:
            raise fuse.FuseOSError(errno.EPERM)

    def rename_child(self, old_name: str, new_name: str, node: fusetree.Node) -> None:
        track_id = None
        if isinstance(node, TrackNode) or isinstance(node, TrackAudioFile):
            track_id = node.id

        if track_id is None:
            raise fuse.FuseOSError(errno.ENOENT)

        try:
            old_position = int(old_name.split(' - ')[0]) - 1
            new_position = int(new_name.split(' - ')[0]) - 1

            new_position = max(min(new_position, len(self.content['tracks']) - 1), 0)
            if new_position > old_position:
                new_position += 1
            print(f'Moving {track_id} from {old_position} to {new_position}')

            self.spotifyfs.spotify.user_playlist_reorder_tracks(
                self.id[0], self.id[1],
                old_position, new_position,
                snapshot_id=self.content['snapshot_id']
            )
            self.invalidate_cache()
        except:
            raise
            raise fuse.FuseOSError(errno.EPERM)

class TrackNode(SpotifyDir):
    content_file = '.track.json'
    image_file = '.track.jpg'

    def fetch_content(self) -> NodeContent:
        return self.spotify.track(self.id)

    def list_files(self, content: NodeContent) -> Iterator[Tuple[str, LazyNode, int]]:
        if content['preview_url'] is not None:
            yield 'sample.mp3', lambda: fusetree.UrllibFile(content['preview_url']), FILE_MODE
        else:
            yield 'sample.mp3', lambda: '', FILE_MODE
        yield 'audio.mp3', lambda: TrackAudioFile(self.spotifyfs, content['id'], FILE_MODE), FILE_MODE


class TrackAudioFile(SpotifyNode):
    def open(self, path, mode):
        return TrackAudioFile.Handle(self, self.spotifyfs, self.id)

    class Handle(fusetree.FileHandle):
        def __init__(self, node, spotifyfs, id):
            super().__init__(node, direct_io = True)
            self.playback = spotifyfs.audio_fetch.play(id)

        def read(self, path, size, offset):
            return self.playback.read(size)

        def release(self, path):
            self.playback.close()


class FollowedArtistsNode(SpotifyDir):
    content_file = '.followed_artists.json'

    def fetch_content(self):
        artists_it = self.spotifyfs.spotify.current_user_followed_artists()['artists']
        artists = artists_it['items']
        while artists_it['next']:
            artists_it = self.spotifyfs.spotify.next(artists_it)['artists']
            artists += artists_it['items']

        return artists

    def list_files(self, content: NodeContent) -> Iterator[Tuple[str, LazyNode, int]]:
        for artist in content:
            filename = artist["name"]
            yield filename, partial(lambda id: self.spotifyfs.getArtist(id), artist['id']), DIR_MODE

    def add_child(self, name_or_node: Union[str, fusetree.Node]):
        artist_id = None
        if isinstance(name_or_node, ArtistNode):
            artist_id = name_or_node.id
        elif isinstance(name_or_node, str):
            results = self.spotifyfs.spotify.search(q=name_or_node, type='artist')
            items = results['artists']['items']
            if len(items) != 0:
                artist_id = items[0]['id']

        if artist_id is None:
            raise fuse.FuseOSError(errno.ENOENT)

        self.spotifyfs.spotify.user_follow_artists([artist_id])
        self.invalidate_cache()

    def remove_child(self, name, node):
        artist_id = None
        if not isinstance(node, ArtistNode):
            raise fuse.FuseOSError(errno.EPERM)

        artist_id = node.id
        self.spotifyfs.spotify.user_unfollow_artists([artist_id])
        self.invalidate_cache()


class UserPlaylistsNode(SpotifyDir):
    # TODO:
    # - Add / Remove / Rename playlist

    content_file = '.playlists.json'

    def fetch_content(self):
        if self.id=='me':
            playlists_it = self.spotifyfs.spotify.current_user_playlists()
        else:
            playlists_it = self.spotifyfs.spotify.user_playlists(self.id)
        playlists = playlists_it['items']
        while playlists_it['next']:
            playlists_it = self.spotifyfs.spotify.next(playlists_it)
            playlists += playlists_it['items']

        return playlists

    def list_files(self, content):
        for playlist in content:
            filename = playlist["name"]
            yield filename, partial(lambda user, id: self.spotifyfs.getPlaylist(user, id), playlist['owner']['id'], playlist['id']), DIR_MODE


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    fusetree.FuseTree(SpotifyFS(), sys.argv[1], foreground=True)
