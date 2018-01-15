#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function

import stat
import errno
import fuse
import os
import urllib2
import inspect
from io import BytesIO
import routefs
from routes import Mapper
from expiringdict import ExpiringDict
import json
import sys
import traceback
import types

import spotipy
import spotipy.oauth2
import spotipy.util

def path2url(path):
    return "file://" + urllib2.pathname2url(os.path.abspath(path))

class SpotifyFS(routefs.RouteFS):
    def __init__(self, *args, **kwargs):
        routefs.RouteFS.__init__(self, *args, **kwargs)
        self.fuse_args.add("allow_other", True)

        # There is a massive performance gain if we cache a directory's contents.
        self.cache = ExpiringDict(max_len=64*1024, max_age_seconds=3600)

        self.token = spotipy.util.prompt_for_user_token(
            '1252589511',
            'user-library-read user-follow-read playlist-read-private playlist-read-collaborative',
            client_id='85fe52cff756410095a3714c028c288b',
            client_secret='822d085d81af4aae9ad800609dcc3706',
            redirect_uri='https://example.com')
        print("token: %s" % self.token)


    def fsinit(self):
        self.spotify = spotipy.Spotify(auth=self.token)
        print("Spotify created")
        print("me: %s" % self.spotify.me())


    def make_map(self):
        m = Mapper()
        m.connect('/', controller='getRoot')
        m.connect('/.id', controller='getIdDir')
        m.connect('/Artists{subpath:(/.*)?}', controller='getCurrentUserArtists')
        m.connect('/Playlists{subpath:(/.*)?}', controller='getCurrentUserPlaylists')


        m.connect('/.id/track', controller='getEmptyDir')
        m.connect('/.id/track/{trackId}{.format:mp3|desktop|json}', controller='getTrack')

        m.connect('/.id/album', controller='getEmptyDir')
        m.connect('/.id/album/{albumId}{subpath:(/.*)?}', controller='getAlbum')

        m.connect('/.id/artist', controller='getEmptyDir')
        m.connect('/.id/artist/{artistId}{subpath:(/.*)?}', controller='getArtist')

        m.connect('/.id/user', controller='getEmptyDir')
        m.connect('/.id/user/{userId}{subpath:(/.*)?}', controller='getUser')

        m.connect('/.id/playlist', controller='getEmptyDir')
        m.connect('/.id/playlist/{userId}_{playlistId}{subpath:(/.*)?}', controller='getPlaylist')

        #m.connect('/.id/user/{user}/playlist/{playlistId}', controller='getPlaylist')
        return m



    def getRoot(self):
        return routefs.Directory(['Artists', 'Playlists'])


    def getIdDir(self):
        return routefs.Directory([])

    def getEmptyDir(self):
        return routefs.Directory([])



    def getTrack(self, trackId, format):
        cache_key = ('track', trackId)
        try:
            track = self.cache[cache_key]
        except:
            print('getTrack %s' % trackId)
            track = self.spotify.track(trackId)
            self.cache[cache_key] = track

        if format == 'json':
            return routefs.File(json.dumps(track, indent=4))

        elif format == 'desktop':
            return routefs.File((inspect.cleandoc(
                u"""
                [Desktop Entry]
                Encoding=UTF-8
                Name=%s
                Type=Link
                URL=%s
                Icon=text-html
                """) % (track['name'], track['external_urls']['spotify'])).encode('utf8'))

        elif format == 'mp3':
            if track['preview_url'] is not None:
                return Urllib1File(track['preview_url'])
            else:
                return routefs.File('')



    def getAlbum(self, albumId, subpath='/'):
        cache_key = ('album', albumId)
        try:
            album = self.cache[cache_key]
        except:
            print('getAlbum %s' % albumId)
            album = self.spotify.album(albumId)

            tracks_it = album['tracks']
            album['tracks'] = tracks_it['items']
            while tracks_it['next']:
                tracks_it = self.spotify.next(tracks_it)
                album['tracks'] += tracks_it['items']

            self.cache[cache_key] = album

        structure = {
            '.album.json': routefs.File(json.dumps(album, indent=4))
        }

        if album['images']:
            structure['image.jpg'] = Urllib1File(album['images'][0]['url'])

        track_numbers = set()
        disc_numbers = set()

        try:
            for track in album['tracks']:
                self.cache[('track', track['id'])] = track
                track_numbers.add(track['track_number'])
                disc_numbers.add(track['disc_number'])

            for track in album['tracks']:
                if len(disc_numbers) > 1:
                    tracklist = structure.setdefault('Disc %d' % track['disc_number'], {})
                else:
                    tracklist = structure

                filename = track['name'] + u'.mp3'
                if len(track_numbers) > 1:
                    filename = u"%02d - %s" % (track['track_number'], filename)

                filename = filename.replace(u'/', u'∕')

                tracklist[filename] = routefs.Symlink('.id/track/' + track['id'] + '.mp3')
        except:
            traceback.print_exc()

        return handleSubpath(structure, subpath)



    def getArtist(self, artistId, subpath='/'):
        cache_key = ('artist', artistId)
        try:
            artist = self.cache[cache_key]
        except:
            print('getArtist %s' % artistId)
            artist = self.spotify.artist(artistId)

            albums_it = self.spotify.artist_albums(artistId)
            artist['albums'] = albums_it['items']
            while albums_it['next']:
                albums_it = self.spotify.next(albums_it)
                artist['albums'] += albums_it['items']

            self.cache[cache_key] = artist


        structure = {
            '.artist.json': routefs.File(json.dumps(artist, indent=4))
        }

        if artist['images']:
            structure['image.jpg'] = Urllib1File(artist['images'][0]['url'])

        try:
            for album in artist['albums']:
                filename = album['name']
                filename = filename.replace(u'/', u'∕')

                structure[filename] = routefs.Symlink('../../album/' + album['id'])
        except:
            traceback.print_exc()

        return handleSubpath(structure, subpath)



    def getUser(self, userId, subpath='/'):
        cache_key = ('user', userId)
        try:
            user = self.cache[cache_key]
        except:
            print('getUser %s' % userId)
            user = self.spotify.user(userId)

            playlists_it = self.spotify.user_playlists(userId, limit=2)
            user['playlists'] = playlists_it['items']
            while playlists_it['next']:
                playlists_it = self.spotify.next(playlists_it)
                user['playlists'] += playlists_it['items']

            self.cache[cache_key] = user


        structure = {
            '.user.json': routefs.File(json.dumps(user, indent=4))
        }

        if user['images']:
            structure['image.jpg'] = Urllib1File(user['images'][0]['url'])

        try:
            for playlist in user['playlists']:
                filename = playlist['name']
                filename = filename.replace(u'/', u'∕')

                structure[filename] = routefs.Symlink('../../playlist/%s_%s' % (userId, playlist['id']))
        except:
            traceback.print_exc()

        return handleSubpath(structure, subpath)


    def getPlaylist(self, userId, playlistId, subpath='/'):
        cache_key = ('playlist', userId, playlistId)
        try:
            playlist = self.cache[cache_key]
        except:
            print('getPlaylist %s:%s' % (userId, playlistId))
            playlist = self.spotify.user_playlist(userId, playlistId)

            tracks_it = playlist['tracks']
            playlist['tracks'] = tracks_it['items']
            while tracks_it['next']:
                tracks_it = self.spotify.next(tracks_it)
                playlist['tracks'] += tracks_it['items']

            playlist['tracks'] = [
                track['track']
                for track in playlist['tracks']
                if not track['is_local']
            ]

            self.cache[cache_key] = playlist


        structure = {
            '.playlist.json': routefs.File(json.dumps(playlist, indent=4))
        }

        if playlist['images']:
            structure['image.jpg'] = Urllib1File(playlist['images'][0]['url'])

        try:
            n = 0
            for track in playlist['tracks']:
                self.cache[('track', track['id'])] = track

                filename = track['name'] + u'.mp3'
                if len(track['artists']) > 0:
                    filename = u', '.join([artist['name'] for artist in track['artists']]) + u' - ' + filename

                n += 1
                filename = u'%03d - %s' % (n, filename)

                filename = filename.replace(u'/', u'∕')

                structure[filename] = routefs.Symlink('../../track/' + track['id'] + '.mp3')

        except:
            traceback.print_exc()

        return handleSubpath(structure, subpath)



    def getCurrentUserPlaylists(self, subpath='/'):
        cache_key = ('currentuser_playlists')
        try:
            playlists = self.cache[cache_key]
        except:
            print('getCurrentUserPlaylists')
            playlists_it = self.spotify.current_user_playlists()
            playlists = playlists_it['items']
            while playlists_it['next']:
                playlists_it = self.spotify.next(playlists_it)
                playlists += playlists_it['items']

            self.cache[cache_key] = playlists


        structure = {
            '.playlists.json': routefs.File(json.dumps(playlists, indent=4))
        }

        try:
            for playlist in playlists:
                filename = playlist['name']
                filename = filename.replace(u'/', u'∕')

                structure[filename] = routefs.Symlink('../.id/playlist/' + playlist['owner']['id'] + '_' + playlist['id'])
        except:
            traceback.print_exc()

        return handleSubpath(structure, subpath)



    def getCurrentUserArtists(self, subpath='/'):
        cache_key = ('currentuser_artists')
        try:
            artists = self.cache[cache_key]
        except:
            print('getCurrentUserArtists')
            artists_it = self.spotify.current_user_followed_artists()['artists']
            artists = artists_it['items']
            while artists_it['next']:
                artists_it = self.spotify.next(artists_it)['artists']
                artists += artists_it['items']

            self.cache[cache_key] = artists


        structure = {
            '.artists.json': routefs.File(json.dumps(artists, indent=4))
        }

        try:
            for artist in artists:
                filename = artist['name']
                filename = filename.replace(u'/', u'∕')

                structure[filename] = routefs.Symlink('../.id/artist/' + artist['id'])

        except:
            traceback.print_exc()

        return handleSubpath(structure, subpath)



def handleSubpath(structure, subpath):
    try:
        for element in path_elements(subpath):
            if type(structure) is dict:
                structure = structure[element]
            else:
                return

    except KeyError:
        return

    if type(structure) is dict:
        return routefs.Directory([
            filename.encode('utf8')
            for filename in structure.keys()
        ])
    else:
        return structure



def path_elements(path):
    return [element for element in path.split('/') if element]



class BufferedFile(routefs.TreeEntry, str):
    """
    A class representing a file that will can be read/write as a big buffer
    """

    default_mode = 0444

    open_files = {}

    class BufferedFileHandle:
        def __init__(self, buffer):
            self.buffer = buffer
            self.dirty = False
            self.refs = 0

    def buffer_size(self):
        """
        This must be fast in order to have responsive directory listing.
        If you cannot make it fast, returning zero is often OK.

        Return None to use buffer_read() as means to fetch the length.

        You can also return -ENOENT and -EIO to signal errors
        """
        return None

    def buffer_read(self):
        """
        Read remote file into a byte buffer.

        Return None to trigger ENOENT and raise some exception to trigger EIO
        """
        raise Exception("Read not supported")

    def buffer_write(self, buffer):
        """
        Write byte buffer into remote file

        Raise some exception to trigger EIO
        """
        raise Exception("Write not supported")

    def cache_key(self):
        return (self.__class__, self)


    def getattr(self):
        st = routefs.RouteStat()
        st.st_mode = stat.S_IFREG | self.mode
        st.st_nlink = 1

        fh = BufferedFile.open_files.get(self.cache_key(), None)
        if fh:
            st.st_size = len(fh.buffer.getvalue())
        else:
            try:
                st.st_size = self.buffer_size()
                if st.st_size is None:
                    st.st_size = len(self.buffer_read())
                elif st.st_size < 0:
                    return st.st_size
            except:
                return -errno.EIO

        return st


    def open(self, flags):
        fh = BufferedFile.open_files.get(self.cache_key(), None)
        if fh is None:
            try:
                buffer = self.buffer_read()
                if buffer is None:
                    return -errno.ENOENT
            except:
                return -errno.EIO

            fh = BufferedFile.BufferedFileHandle(BytesIO(buffer))
            BufferedFile.open_files[self.cache_key()] = fh

        fh.refs += 1
        return fh


    def release(self, flags, fh):
        fh.refs -= 1
        if fh.refs == 0:
            del BufferedFile.open_files[self.cache_key()]
            return self.flush(fh)


    def flush(self, fh):
        if fh.dirty:
            try:
                self.buffer_write(fh.buffer.getvalue())
            except:
                return -errno.EIO
        return 0


    def truncate(self, len):
        fh = self.open(0)
        if isinstance(fh, int):
            return fh  #error code

        fh.dirty = True
        fh.buffer.truncate(len)
        return self.release(0, fh)


    def read(self, length, offset, fh):
        fh.buffer.seek(offset)
        return fh.buffer.read(length)


    def write(self, buffer, offset, fh):
        fh.dirty = True
        fh.buffer.seek(offset)
        fh.buffer.write(buffer)
        return len(buffer)



class Urllib1File(BufferedFile):
    open_files = {}

    """
    A dummy class representing a file that will be fetched via urllib2 that should be a file
    """
    default_mode = 0444

    def buffer_size(self):
        request = urllib2.Request(self)
        request.get_method = lambda : 'HEAD'
        try:
            return int(urllib2.urlopen(request).info()['content-length'])
        except:
            return None

    def buffer_read(self):
        return urllib2.urlopen(self).read()


if __name__ == '__main__':
    routefs.main(SpotifyFS)
