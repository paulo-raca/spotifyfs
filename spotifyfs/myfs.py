#!/usr/bin/python3
# -*- coding: utf-8 -*-

from stat import S_IFDIR, S_IFLNK, S_IFREG
import sys
import fuse
import logging
import errno
import urllib
from time import time
from expiringdict import ExpiringDict

class LoggingFs(fuse.Operations):
    log = logging.getLogger('fuse.log-mixin')

    def __init__(self, operations):
        self.operations = operations

    def __call__(self, op, path, *args):
        self.log.debug('-> %s %s %s', op, path, repr(args))
        ret = '[Unhandled Exception]'
        try:
            ret = self.operations.__call__(op, path, *args)
            return ret
        except OSError as e:
            ret = str(e)
            raise
        finally:
            self.log.debug('<- %s %s', op, '%d bytes' % len(ret) if isinstance(ret, bytes) else repr(ret))




class FsEntry(fuse.Operations):
    log = logging.getLogger('fuse.fsentry')
    def __call__(self, op, path, *args):
        path_elements = path.split('/', 2)[1:]
        if path_elements != ['']:
            child = self[path_elements[0]]


            if child is None:
              raise fuse.FuseOSError(errno.ENOENT)
            elif type(child) is bytes:
              child = ReadOnlyFileEntry(child)
            elif type(child) is str:
              child = ReadOnlyFileEntry(child.encode('utf8'))
            elif type(child) is dict:
              child = DirEntry(child)

            return child(op, '/' + (path_elements[1] if len(path_elements) > 1 else ''), *args)
        else:
            return super(FsEntry, self).__call__(op, path, *args)


class DirEntry(FsEntry):
    def __init__(self, contents):
        self.contents = contents

    def __getitem__(self, key):
        return self.contents.get(key, None)

    def getattr(self, path, fh=None):
        now = time()
        return dict(
          st_mode=(S_IFDIR | 0o755),
          st_nlink=2,
          st_size=0,
          st_ctime=now,
          st_mtime=now,
          st_atime=now)

    def readdir(self, path, fh):
        yield '.'
        yield '..'
        for i in self.contents:
            yield i


class ReadOnlyFileEntry(FsEntry):
    def __init__(self, contents):
        self.contents = contents

    def getattr(self, path, fh=None):
        now = time()
        return dict(
          st_mode=(S_IFREG | 0o755),
          st_nlink=1,
          st_size=len(self.contents),
          st_ctime=now,
          st_mtime=now,
          st_atime=now)

    def read(self, path, size, offset, fh):
        return self.contents[offset:offset + size]



class Urllib1FileEntry(FsEntry):
    next_fh = 0
    open_files = {}
    cached_size = ExpiringDict(max_len=64*1024, max_age_seconds=300)

    def __init__(self, url, fake_size=None):
        self.url = url
        self.fake_size = fake_size

    def open(self, path, fi):
        fh = Urllib1FileEntry.next_fh
        Urllib1FileEntry.next_fh += 1
        with urllib.request.urlopen(self.url) as response:
            data = response.read()
            Urllib1FileEntry.open_files[fh] = data
            Urllib1FileEntry.cached_size[self.url] = len(data)
        fi.fh = fh

    def release(self, path, fi):
        del Urllib1FileEntry.open_files[fi.fh]

    def read(self, path, size, offset, fi):
        return Urllib1FileEntry.open_files[fi.fh][offset:offset + size]

    def getSize(self, fi):
        # Try to get size from buffer is the file is open
        if fi is not None:
            return len(Urllib1FileEntry.open_files[fi.fh])

        # Try to get cached file size
        try:
            return Urllib1FileEntry.cached_size[self.url]
        except:
            pass

        # Return default file size -- Sometimes a lie, but it's faster than accessing the network
        if self.fake_size is not None:
            return self.fake_size

        # use a HEAD request to fetch file size
        try:
            request = urllib.request.Request(self.url, method='HEAD')
            with urllib.request.urlopen(request) as response:
                size = int(response.info()['content-length'])
                Urllib1FileEntry.cached_size[self.url] = size
                return size
        except:
            return 0

    def getattr(self, path, fi=None):
        now = time()
        return dict(
          st_mode=(S_IFREG | 0o755),
          st_nlink=1,
          st_size=self.getSize(fi),
          st_ctime=now,
          st_mtime=now,
          st_atime=now)




fs = DirEntry({
    'a': '1ŋ€?たことから「化学兵器の父」と呼ばれることもある。……',
    'b': {
      'c': 'foobar',
      'd': 'meh',
    }
})




if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    fuse.FUSE(LoggingFs(fs), sys.argv[1], foreground=True)
