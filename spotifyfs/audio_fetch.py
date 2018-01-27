#!/usr/bin/python
# -*- coding: utf-8 -*-

from librespot import Session, SpotifyId
import os
import threading
import traceback
import time
from io import BytesIO

class AudioSink:
  def __init__(self):
      self.target = None

  def write(self, buf):
      try:
          #print('<', end='', flush=True)
          with self.target.cond:
              self.target.buffer = self.target.buffer + buf
              self.target.cond.notify_all()
          #print('>', end='', flush=True)
      except:
          traceback.print_exc()


class SpotifyAudioFetcher():
    def __init__(self):
        self.semaphore = threading.Semaphore()
        self.sink = AudioSink()
        self.session = Session.connect('1252589511', '32413399', self.sink).result()
        self.player = self.session.player()


    def play(self, trackId):
        class reader:
            def __init__(self, audio_fetcher):
                self.audio_fetcher = audio_fetcher
                self.buffer = None
                self.playing = False
                self.cond = threading.Condition()

            def buf_len(self):
                with self.cond:
                    if self.buffer is not None:
                        return len(self.buffer)
                    else:
                        return 0

            def read(self, size, offset):
                with self.cond:
                    # Lazy open
                    if self.buffer is None:
                        print('Waiting to play %s' % trackId)
                        self.audio_fetcher.semaphore.acquire()
                        self.playing = True
                        print('Playing %s' % trackId)
                        self.buffer = b''
                        self.audio_fetcher.sink.target = self
                        self.future = self.audio_fetcher.player.load(SpotifyId(trackId))
                        self.future.add_done_callback(lambda x: self._audio_ended())

                    # Wait for data
                    while self.playing and len(self.buffer) <= offset + size:
                        #print('Buffer underflow... %d/%d' % (offset, len(self.buffer)))
                        self.cond.wait()

                    #print('Buffer infill: %d/%d' % (offset, len(self.buffer)))
                    return self.buffer[offset:offset+size]

            def _audio_ended(self):
                with self.cond:
                    print('Audio stream ended: %s', trackId)
                    # Release audio_fetcher'
                    self.audio_fetcher.target = None
                    self.audio_fetcher.semaphore.release()

                    # Signal to anyone waiting on the cond
                    self.playing = False
                    self.cond.notify_all()

            def close(self):
                print('File reader closed for %s' % trackId)
                with self.cond:
                    if self.playing:
                        self.audio_fetcher.player.stop()

            def wait(self):
                if self.future:
                    self.future.result()

        return reader(self)


if __name__ == '__main__':
    fetcher = SpotifyAudioFetcher()
    player1 = fetcher.play('2dA7eKXUzw1Ndc78kKRefH')
    print(player1.read(10))
    print(player1.read(10))
    print(player1.read(10))
    print(player1.read(10))
    player1.wait()
