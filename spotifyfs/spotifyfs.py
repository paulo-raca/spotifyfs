#!/usr/bin/python
# -*- coding: utf-8 -*-

import spotipy
import spotipy.oauth2
import spotipy.util

from librespot import Session, SpotifyId

from expiringdict import ExpiringDict
from functools import partial
from stat import S_IFDIR, S_IFLNK, S_IFREG

import inspect
import sys
import json
import time

import fuse
import logging
import myfs
import audio_fetch

class SpotifyFS():
    def __init__(self):
        # There is a massive performance gain if we cache a directory's contents.
        self.cache = ExpiringDict(max_len=64*1024, max_age_seconds=3600)

        self.token = spotipy.util.prompt_for_user_token(
            '1252589511',
            'user-library-read user-follow-read playlist-read-private playlist-read-collaborative',
            client_id='85fe52cff756410095a3714c028c288b',
            client_secret='822d085d81af4aae9ad800609dcc3706',
            redirect_uri='https://example.com')

        self.spotify = spotipy.Spotify(auth=self.token)
        print("me: %s" % self.spotify.me())

        self.audio_fetch = audio_fetch.SpotifyAudioFetcher()

        self.rootEntry = SpotifyFS.RootEntry(self)
        self.artistEntries = {}
        self.albumEntries = {}
        self.trackEntries = {}
        self.playlistEntries = {}


    class AudioStreamFile(myfs.FsEntry):
        next_fh = 0
        open_files = {}

        def __init__(self, spotifyfs, trackInfo):
            self.spotifyfs = spotifyfs
            self.trackInfo = trackInfo

        def getattr(self, path, fi=None):
            now = time.time()
            filelen = 1
            if fi is not None:
                filelen = SpotifyFS.AudioStreamFile.open_files[fi.fh].buf_len()

            return dict(
              st_mode=(S_IFREG | 0o755),
              st_nlink=1,
              st_size=max(filelen, 1),
              st_ctime=now,
              st_mtime=now,
              st_atime=now)

        def open(self, path, fi):
            fh = SpotifyFS.AudioStreamFile.next_fh
            SpotifyFS.AudioStreamFile.next_fh += 1

            SpotifyFS.AudioStreamFile.open_files[fh] = self.spotifyfs.audio_fetch.play(self.trackInfo['id'])

            fi.direct_io = True
            fi.fh = fh

        def release(self, path, fi):
            SpotifyFS.AudioStreamFile.open_files[fi.fh].close()
            del SpotifyFS.AudioStreamFile.open_files[fi.fh]

        def read(self, path, size, offset, fi):
            return SpotifyFS.AudioStreamFile.open_files[fi.fh].read(size, offset)


    class DirEntry(myfs.DirEntry):
        raw_file = '.data.json'
        image_file = None
        default_image = 'https://www1-lw.xda-cdn.com/files/2013/09/music.jpg'

        def __init__(self, spotifyfs, id=None):
            self.spotifyfs = spotifyfs
            self.id = id
            self.readdir_called = False
            super(SpotifyFS.DirEntry, self).__init__({})

        def getRawData(self):
            return {}

        def listFiles(self):
            return []

        def getNewEntry(self, name):
            return None

        def __getitem__(self, name):
            if name == self.raw_file:
                return json.dumps(self.getRawData(), indent=4)
            elif name == self.image_file:
                try:
                    return myfs.Urllib1FileEntry(self.getRawData()['images'][0]['url'], fake_size=1024)
                except:
                    return myfs.Urllib1FileEntry(self.default_image, fake_size=1024)

            elif name == '.directory':
                return inspect.cleandoc("""
                    [Desktop Entry]
                    Name={name}
                    Comment={comment}
                    Icon=./{icon}
                    Type=Directory
                    """.format(name='Foobar', comment='fooo', icon=self.image_file))

            if not self.readdir_called:
                list(self.readdir('/', None))

            gen = self.contents.get(name, None)
            if gen is not None:
                return gen()
            else:
                newEntry = self.getNewEntry(name)
                if newEntry is not None:
                    self.contents[name] = newEntry
                    return newEntry()


        def readdir(self, path, fh):
            yield '.'
            yield '..'

            for filename, gen in self.listFiles():
                filename = filename.replace('/', '∕')
                self.contents[filename] = gen
                yield filename

            yield '.directory'
            if self.raw_file is not None:
                yield self.raw_file
            if self.image_file is not None:
                yield self.image_file

            self.readdir_called = True

    def getArtist(self, id):
        try:
            return self.artistEntries[id]
        except:
            artistEntry = self.ArtistEntry(self, id)
            self.artistEntries[id] = artistEntry
            return artistEntry

    def getAlbum(self, id):
        try:
            return self.albumEntries[id]
        except:
            albumEntry = self.AlbumEntry(self, id)
            self.albumEntries[id] = albumEntry
            return albumEntry

    def getPlaylist(self, userId, playlistId):
        try:
            return self.playlistEntries[(userId, playlistId)]
        except:
            playlistEntry = self.PlaylistEntry(self, (userId, playlistId))
            self.playlistEntries[(userId, playlistId)] = playlistEntry
            return playlistEntry

    def getTrack(self, id):
        try:
            return self.trackEntries[id]
        except:
            trackEntry = self.TrackEntry(self, id)
            self.trackEntries[id] = trackEntry
            return trackEntry



    class RootEntry(DirEntry):
        raw_file = None

        def __init__(self, spotifyfs):
            super(SpotifyFS.RootEntry, self).__init__(spotifyfs)
            self.artists = self.spotifyfs.CurrentUserArtistsEntry(self.spotifyfs)
            self.playlists = self.spotifyfs.CurrentUserPlaylistsEntry(self.spotifyfs)

        def listFiles(self):
            yield 'Artists', lambda: self.artists
            yield 'Playlists', lambda: self.playlists


    class TrackEntry(DirEntry):
        raw_file = '.track.json'
        image_file = '.track.jpg'

        def getRawData(self):
            cache_key = ('track', self.id)
            try:
                track = self.spotifyfs.cache[cache_key]
            except:
                print('getTrack %s' % self.id)
                track = self.spotify.track(trackId)
                self.spotifyfs.cache[cache_key] = track
            return track

        def listFiles(self):
            track = self.getRawData()
            #if track['preview_url'] is not None:
                #yield 'sample.mp3', lambda: myfs.Urllib1FileEntry(track['preview_url'], fake_size=1024)
            #else:
                #yield 'sample.mp3', lambda: ''
            yield 'sample.mp3', lambda: SpotifyFS.AudioStreamFile(self.spotifyfs, track)


    class ArtistEntry(DirEntry):
        raw_file = '.artist.json'
        image_file = '.artist.jpg'

        def getRawData(self):
            cache_key = ('artist', self.id)
            try:
                artist = self.spotifyfs.cache[cache_key]
            except:
                print('getArtist %s' % self.id)
                artist = self.spotifyfs.spotify.artist(self.id)

                albums_it = self.spotifyfs.spotify.artist_albums(self.id, limit=50)
                artist['albums'] = albums_it['items']
                while albums_it['next']:
                    albums_it = self.spotifyfs.spotify.next(albums_it)
                    artist['albums'] += albums_it['items']

                self.spotifyfs.cache[cache_key] = artist
            return artist

        def listFiles(self):
            for album in self.getRawData()['albums']:
                filename = album['name']
                yield filename, partial(lambda id: self.spotifyfs.getAlbum(id), album['id'])



    class AlbumEntry(DirEntry):
        raw_file = '.album.json'
        image_file = '.album.jpg'

        def getRawData(self):
            cache_key = ('album', self.id)
            try:
                album = self.spotifyfs.cache[cache_key]
            except:
                print('getAlbum %s' % self.id)
                album = self.spotifyfs.spotify.album(self.id)

                tracks_it = album['tracks']
                album['tracks'] = tracks_it['items']
                while tracks_it['next']:
                    tracks_it = self.spotifyfs.spotify.next(tracks_it)
                    album['tracks'] += tracks_it['items']

                for track in album['tracks']:
                    self.spotifyfs.cache[('track', track['id'])] = track

                self.spotifyfs.cache[cache_key] = album
            return album

        def listFiles(self):
            tracks = self.getRawData()['tracks']

            track_numbers = set()
            disc_numbers = set()

            for track in tracks:
                track_numbers.add(track['track_number'])
                disc_numbers.add(track['disc_number'])

            for track in tracks:
                filename = track['name'] + '.mp3'
                if len(track_numbers) > 1:
                    filename = "%02d - %s" % (track['track_number'], filename)

                yield filename, partial(lambda id: self.spotifyfs.getTrack(id)['sample.mp3'], track['id'])



    class PlaylistEntry(DirEntry):
        raw_file = '.playlist.json'
        image_file = '.playlist.jpg'

        def getRawData(self):
            userId, playlistId = self.id
            cache_key = ('playlist', userId, playlistId)
            try:
                playlist = self.spotifyfs.cache[cache_key]
            except:
                print('getPlaylist %s/%s' % (userId, playlistId))
                playlist = self.spotifyfs.spotify.user_playlist(userId, playlistId)

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
                    self.spotifyfs.cache[('track', track['id'])] = track

                self.spotifyfs.cache[cache_key] = playlist
            return playlist

        def listFiles(self):
            n = 0

            for track in self.getRawData()['tracks']:
                filename = track['name'] + '.mp3'
                if len(track['artists']) > 0:
                    filename = ', '.join([artist['name'] for artist in track['artists']]) + ' - ' + filename

                n += 1
                filename = '%03d - %s' % (n, filename)
                yield filename, partial(lambda id: self.spotifyfs.getTrack(id)['sample.mp3'], track['id'])



    class CurrentUserArtistsEntry(DirEntry):
        raw_file = '.currentuser_artists.json'

        def getRawData(self):
            cache_key = ('currentuser_artists')
            try:
                artists = self.spotifyfs.cache[cache_key]
            except:
                print('getCurrentUserArtists')
                artists_it = self.spotifyfs.spotify.current_user_followed_artists()['artists']
                artists = artists_it['items']
                while artists_it['next']:
                    artists_it = self.spotifyfs.spotify.next(artists_it)['artists']
                    artists += artists_it['items']

                self.spotifyfs.cache[cache_key] = artists

            return artists


        def listFiles(self):
            for artist in self.getRawData():
                filename = artist["name"]
                yield filename, partial(lambda id: self.spotifyfs.getArtist(id), artist['id'])

        def getNewEntry(self, name):
            results = self.spotifyfs.spotify.search(q=name, type='artist')
            items = results['artists']['items']
            if len(items) > 0:
                return lambda: self.spotifyfs.getArtist(items[0]['id'])




    class CurrentUserPlaylistsEntry(DirEntry):
        raw_file = '.currentuser_playlists.json'

        def getRawData(self):
            cache_key = ('currentuser_playlists')
            try:
                playlists = self.spotifyfs.cache[cache_key]
            except:
                print('getCurrentUserPlaylists')
                playlists_it = self.spotifyfs.spotify.current_user_playlists()
                playlists = playlists_it['items']
                while playlists_it['next']:
                    playlists_it = self.spotifyfs.spotify.next(playlists_it)
                    playlists += playlists_it['items']

                self.spotifyfs.cache[cache_key] = playlists

            return playlists


        def listFiles(self):
            for playlist in self.getRawData():
                filename = playlist["name"]
                yield filename, partial(lambda user, id: self.spotifyfs.getPlaylist(user, id), playlist['owner']['id'], playlist['id'])




    #def getCurrentUserPlaylists(self, subpath='/'):
        #cache_key = ('currentuser_playlists')
        #try:
            #playlists = self.cache[cache_key]
        #except:
            #print('getCurrentUserPlaylists')
            #playlists_it = self.spotify.current_user_playlists()
            #playlists = playlists_it['items']
            #while playlists_it['next']:
                #playlists_it = self.spotify.next(playlists_it)
                #playlists += playlists_it['items']

            #self.cache[cache_key] = playlists


        #structure = {
            #'.playlists.json': routefs.File(json.dumps(playlists, indent=4))
        #}

        #try:
            #for playlist in playlists:
                #filename = playlist['name']
                #filename = filename.replace(u'/', u'∕')

                #structure[filename] = routefs.Symlink('../.id/playlist/' + playlist['owner']['id'] + '_' + playlist['id'])
        #except:
            #traceback.print_exc()






    #def getTrack(self, trackId, format):
        #cache_key = ('track', trackId)
        #try:
            #track = self.cache[cache_key]
        #except:
            #print('getTrack %s' % trackId)
            #track = self.spotify.track(trackId)
            #self.cache[cache_key] = track

        #if format == 'json':
            #return routefs.File(json.dumps(track, indent=4))

        #elif format == 'desktop':
            #return routefs.File((inspect.cleandoc(
                #u"""
                #[Desktop Entry]
                #Encoding=UTF-8
                #Name=%s
                #Type=Link
                #URL=%s
                #Icon=text-html
                #""") % (track['name'], track['external_urls']['spotify'])).encode('utf8'))

        #elif format == 'mp3':
            #if track['preview_url'] is not None:
                #return Urllib1File(track['preview_url'])
            #else:
                #return routefs.File('')



    #def getAlbum(self, albumId, subpath='/'):
        #cache_key = ('album', albumId)
        #try:
            #album = self.cache[cache_key]
        #except:
            #print('getAlbum %s' % albumId)
            #album = self.spotify.album(albumId)

            #tracks_it = album['tracks']
            #album['tracks'] = tracks_it['items']
            #while tracks_it['next']:
                #tracks_it = self.spotify.next(tracks_it)
                #album['tracks'] += tracks_it['items']

            #self.cache[cache_key] = album

        #structure = {
            #'.album.json': routefs.File(json.dumps(album, indent=4))
        #}

        #if album['images']:
            #structure['image.jpg'] = Urllib1File(album['images'][0]['url'])

        #track_numbers = set()
        #disc_numbers = set()

        #try:
            #for track in album['tracks']:
                #self.cache[('track', track['id'])] = track
                #track_numbers.add(track['track_number'])
                #disc_numbers.add(track['disc_number'])

            #for track in album['tracks']:
                #if len(disc_numbers) > 1:
                    #tracklist = structure.setdefault('Disc %d' % track['disc_number'], {})
                #else:
                    #tracklist = structure

                #filename = track['name'] + u'.mp3'
                #if len(track_numbers) > 1:
                    #filename = u"%02d - %s" % (track['track_number'], filename)

                #filename = filename.replace(u'/', u'∕')

                #tracklist[filename] = routefs.Symlink('.id/track/' + track['id'] + '.mp3')
        #except:
            #traceback.print_exc()

        #return handleSubpath(structure, subpath)



    #def getArtist(self, artistId, subpath='/'):
        #cache_key = ('artist', artistId)
        #try:
            #artist = self.cache[cache_key]
        #except:
            #print('getArtist %s' % artistId)
            #artist = self.spotify.artist(artistId)

            #albums_it = self.spotify.artist_albums(artistId)
            #artist['albums'] = albums_it['items']
            #while albums_it['next']:
                #albums_it = self.spotify.next(albums_it)
                #artist['albums'] += albums_it['items']

            #self.cache[cache_key] = artist


        #structure = {
            #'.artist.json': routefs.File(json.dumps(artist, indent=4))
        #}

        #if artist['images']:
            #structure['image.jpg'] = Urllib1File(artist['images'][0]['url'])

        #try:
            #for album in artist['albums']:
                #filename = album['name']
                #filename = filename.replace(u'/', u'∕')

                #structure[filename] = routefs.Symlink('../../album/' + album['id'])
        #except:
            #traceback.print_exc()

        #return handleSubpath(structure, subpath)



    #def getUser(self, userId, subpath='/'):
        #cache_key = ('user', userId)
        #try:
            #user = self.cache[cache_key]
        #except:
            #print('getUser %s' % userId)
            #user = self.spotify.user(userId)

            #playlists_it = self.spotify.user_playlists(userId, limit=2)
            #user['playlists'] = playlists_it['items']
            #while playlists_it['next']:
                #playlists_it = self.spotify.next(playlists_it)
                #user['playlists'] += playlists_it['items']

            #self.cache[cache_key] = user


        #structure = {
            #'.user.json': routefs.File(json.dumps(user, indent=4))
        #}

        #if user['images']:
            #structure['image.jpg'] = Urllib1File(user['images'][0]['url'])

        #try:
            #for playlist in user['playlists']:
                #filename = playlist['name']
                #filename = filename.replace(u'/', u'∕')

                #structure[filename] = routefs.Symlink('../../playlist/%s_%s' % (userId, playlist['id']))
        #except:
            #traceback.print_exc()

        #return handleSubpath(structure, subpath)


    #def getPlaylist(self, userId, playlistId, subpath='/'):
        #cache_key = ('playlist', userId, playlistId)
        #try:
            #playlist = self.cache[cache_key]
        #except:
            #print('getPlaylist %s:%s' % (userId, playlistId))
            #playlist = self.spotify.user_playlist(userId, playlistId)

            #tracks_it = playlist['tracks']
            #playlist['tracks'] = tracks_it['items']
            #while tracks_it['next']:
                #tracks_it = self.spotify.next(tracks_it)
                #playlist['tracks'] += tracks_it['items']

            #playlist['tracks'] = [
                #track['track']
                #for track in playlist['tracks']
                #if not track['is_local']
            #]

            #self.cache[cache_key] = playlist


        #structure = {
            #'.playlist.json': routefs.File(json.dumps(playlist, indent=4))
        #}

        #if playlist['images']:
            #structure['image.jpg'] = Urllib1File(playlist['images'][0]['url'])

        #try:
            #n = 0
            #for track in playlist['tracks']:
                #self.cache[('track', track['id'])] = track

                #filename = track['name'] + u'.mp3'
                #if len(track['artists']) > 0:
                    #filename = u', '.join([artist['name'] for artist in track['artists']]) + u' - ' + filename

                #n += 1
                #filename = u'%03d - %s' % (n, filename)

                #filename = filename.replace(u'/', u'∕')

                #structure[filename] = routefs.Symlink('../../track/' + track['id'] + '.mp3')

        #except:
            #traceback.print_exc()

        #return handleSubpath(structure, subpath)



    #def getCurrentUserPlaylists(self, subpath='/'):
        #cache_key = ('currentuser_playlists')
        #try:
            #playlists = self.cache[cache_key]
        #except:
            #print('getCurrentUserPlaylists')
            #playlists_it = self.spotify.current_user_playlists()
            #playlists = playlists_it['items']
            #while playlists_it['next']:
                #playlists_it = self.spotify.next(playlists_it)
                #playlists += playlists_it['items']

            #self.cache[cache_key] = playlists


        #structure = {
            #'.playlists.json': routefs.File(json.dumps(playlists, indent=4))
        #}

        #try:
            #for playlist in playlists:
                #filename = playlist['name']
                #filename = filename.replace(u'/', u'∕')

                #structure[filename] = routefs.Symlink('../.id/playlist/' + playlist['owner']['id'] + '_' + playlist['id'])
        #except:
            #traceback.print_exc()

        #return handleSubpath(structure, subpath)



    #def getCurrentUserArtists(self, subpath='/'):
        #cache_key = ('currentuser_artists')
        #try:
            #artists = self.cache[cache_key]
        #except:
            #print('getCurrentUserArtists')
            #artists_it = self.spotify.current_user_followed_artists()['artists']
            #artists = artists_it['items']
            #while artists_it['next']:
                #artists_it = self.spotify.next(artists_it)['artists']
                #artists += artists_it['items']

            #self.cache[cache_key] = artists


        #structure = {
            #'.artists.json': routefs.File(json.dumps(artists, indent=4))
        #}

        #try:
            #for artist in artists:
                #filename = artist['name']
                #filename = filename.replace(u'/', u'∕')

                #structure[filename] = routefs.Symlink('../.id/artist/' + artist['id'])

        #except:
            #traceback.print_exc()

        #return handleSubpath(structure, subpath)



if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(myfs.LoggingFs(SpotifyFS().rootEntry), sys.argv[1], foreground=True, raw_fi=True)
