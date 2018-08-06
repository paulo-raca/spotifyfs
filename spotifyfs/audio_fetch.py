#!/usr/bin/python
# -*- coding: utf-8 -*-

from librespot import Session, SpotifyId
import os
import asyncio
import traceback
import time
import sys
from io import BytesIO
import subprocess
from lame import Lame
import numpy as np
import math

class LameSink:
    def __init__(self):
        self.target = None

    def write(self, buf):
        try:
            buf = np.frombuffer(buf, np.int16)

            asyncio.run_coroutine_threadsafe(
                    self.target._load_chunk(buf),
                    loop = self.target.audio_fetcher.loop).result()
        except:
            traceback.print_exc()
            raise

class SpotifyAudioFetcher():
    def __init__(self, loop):
        self.loop = loop
        self.semaphore = asyncio.Semaphore()
        self.sink = LameSink()
        self.session = Session.connect('1252589511', '32413399', self.sink).result()
        self.player = self.session.player()


    def play(self, trackId, lame_args={}):
        class reader:
            def __init__(self, audio_fetcher):
                self.audio_fetcher = audio_fetcher
                self.lame = None
                self.buf = b''
                self.load_future = None
                self.finished = False
                self.error = False
                self.cond = asyncio.Condition()

            async def ensure_playing(self):
                async with self.cond:
                    if not self.load_future:

                        print('Waiting to play %s' % trackId)
                        self.audio_fetcher.semaphore.acquire()
                        print('Playing %s' % trackId)

                        self.lame = Lame(**lame_args)
                        self.lame.init_params()

                        self.audio_fetcher.sink.target = self

                        load_future = self.audio_fetcher.player.load(SpotifyId(trackId))
                        self.load_future = asyncio.futures.wrap_future(load_future, loop = self.audio_fetcher.loop)
                        def done_cb(fut):
                            x = asyncio.run_coroutine_threadsafe(
                                    self._load_complete(fut.exception()),
                                    loop = self.audio_fetcher.loop)
                        self.load_future.add_done_callback(done_cb)

            async def read(self, offset, length, full=False):
                await self.ensure_playing()

                async with self.cond:
                    min_buf_size = offset + length if full else offset + 1

                    # Wait until: Enough data is available -OR- the strean is complete -OR- there was an error
                    await self.cond.wait_for(lambda: self.finished or len(self.buf) >= min_buf_size)

                    # raise exception if there was an error before the desired chunk was fetched
                    if len(self.buf) < min_buf_size:
                        self.load_future.result()

                    # return the desired chunk
                    return self.buf[offset:offset+length]


            async def _load_chunk(self, buf):
                #Append data to encoding
                encoded = self.lame.encode_buffer(buf)
                async with self.cond:
                    self.buf += encoded
                    self.cond.notify_all()


            async def _load_complete(self, error):
                print('Audio stream ended:', trackId)

                # Release audio_fetcher to play next track
                self.audio_fetcher.sink.target = None
                self.audio_fetcher.semaphore.release()

                #Finish encoding
                encoded = self.lame.encode_flush_nogap()

                async with self.cond:
                    self.buf += encoded
                    self.finished = True
                    if self.error is None and error:
                        self.error = error
                    self.cond.notify_all()
                    print('Audio stream ended2')

            async def close(self):
                print('File reader closed for %s' % trackId)
                async with self.cond:
                    if not self.finished:
                        self.error = asyncio.CancelledError()
                        if self.load_future:
                            self.audio_fetcher.player.stop()

            async def wait(self):
                await self.ensure_playing()
                async with self.cond:
                    await self.cond.wait_for(lambda: self.finished)
                    if self.error:
                        raise Exception("Failed to fetch music")
                    return self.buf



        return reader(self)


if __name__ == '__main__':
    async def main():
        fetcher = SpotifyAudioFetcher(loop)
        player1 = fetcher.play('1Bp4LH1sCG80HQWfBhjfff')
        mp3 = await player1.wait()
        with open('foo.mp3', 'wb') as f:
            f.write(mp3)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.close()
