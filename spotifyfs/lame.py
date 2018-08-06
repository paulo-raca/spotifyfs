from ctypes import *
import numpy as np
from enum import Enum

class MpegMode(Enum):
    STEREO        = 0
    JOINT_STEREO  = 1
    DUAL_CHANNEL  = 2  # LAME doesn't supports this!
    MONO          = 3
    NOT_SET       = 4
    MAX_INDICATOR = 5  # Don't use this! It's used for sanity checks.

class Lib(CDLL):
    class lame_global_struct(Structure):
        pass
    lame_t = POINTER(lame_global_struct)
    lame_report_function = CFUNCTYPE(None, c_char_p, c_void_p)

    def __init__(self, path='libmp3lame.so'):
        super(Lib, self).__init__(path)

        self.lame_init.argtypes = ()
        self.lame_init.restype = Lib.lame_t


        self.lame_set_num_samples.argtypes = (Lib.lame_t, c_ulong)
        self.lame_set_num_samples.restype = c_int


        self.lame_get_num_samples.argtypes = (Lib.lame_t,)
        self.lame_get_num_samples.restype = c_ulong


        self.lame_set_in_samplerate.argtypes = (Lib.lame_t, c_int)
        self.lame_set_in_samplerate.restype = c_int

        self.lame_get_in_samplerate.argtypes = (Lib.lame_t,)
        self.lame_get_in_samplerate.restype = c_int


        self.lame_set_num_channels.argtypes = (Lib.lame_t, c_int)
        self.lame_set_num_channels.restype = c_int

        self.lame_get_num_channels.argtypes = (Lib.lame_t,)
        self.lame_get_num_channels.restype = c_int


        self.lame_set_scale.argtypes = (Lib.lame_t, c_float)
        self.lame_set_scale.restype = c_int

        self.lame_get_scale.argtypes = (Lib.lame_t,)
        self.lame_get_scale.restype = c_float


        self.lame_set_scale_left.argtypes = (Lib.lame_t, c_float)
        self.lame_set_scale_left.restype = c_int

        self.lame_get_scale_left.argtypes = (Lib.lame_t,)
        self.lame_get_scale_left.restype = c_float


        self.lame_set_scale_right.argtypes = (Lib.lame_t, c_float)
        self.lame_set_scale_right.restype = c_int

        self.lame_get_scale_right.argtypes = (Lib.lame_t,)
        self.lame_get_scale_right.restype = c_float


        self.lame_set_out_samplerate.argtypes = (Lib.lame_t, c_int)
        self.lame_set_out_samplerate.restype = c_int

        self.lame_get_out_samplerate.argtypes = (Lib.lame_t,)
        self.lame_get_out_samplerate.restype = c_int


        self.lame_set_brate.argtypes = (Lib.lame_t, c_int)
        self.lame_set_brate.restype = c_int

        self.lame_get_brate.argtypes = (Lib.lame_t,)
        self.lame_get_brate.restype = c_int


        self.lame_set_compression_ratio.argtypes = (Lib.lame_t, c_float)
        self.lame_set_compression_ratio.restype = c_int

        self.lame_get_compression_ratio.argtypes = (Lib.lame_t,)
        self.lame_get_compression_ratio.restype = c_float


        self.lame_set_mode.argtypes = (Lib.lame_t, c_int)
        self.lame_set_mode.restype = c_int

        self.lame_get_mode.argtypes = (Lib.lame_t,)
        self.lame_get_mode.restype = c_int


        self.lame_set_quality.argtypes = (Lib.lame_t, c_int)
        self.lame_set_quality.restype = c_int

        self.lame_get_quality.argtypes = (Lib.lame_t,)
        self.lame_get_quality.restype = c_int


        self.lame_init_params.argtypes = (Lib.lame_t,)
        self.lame_init_params.restype = c_int


        self.lame_print_config.argtypes = (Lib.lame_t,)
        self.lame_print_config.restype = None


        self.lame_print_internals.argtypes = (Lib.lame_t,)
        self.lame_print_internals.restype = None


        self.lame_encode_buffer.argtypes = (Lib.lame_t, POINTER(c_short), POINTER(c_short), c_int, POINTER(c_byte), c_int)
        self.lame_encode_buffer.restype = c_int


        self.lame_encode_buffer_interleaved.argtypes = (Lib.lame_t, POINTER(c_short), c_int, POINTER(c_byte), c_int)
        self.lame_encode_buffer_interleaved.restype = c_int


        self.lame_encode_flush.argtypes = (Lib.lame_t, POINTER(c_byte), c_int)
        self.lame_encode_flush.restype = c_int


        self.lame_encode_flush_nogap.argtypes = (Lib.lame_t, POINTER(c_byte), c_int)
        self.lame_encode_flush_nogap.restype = c_int


        self.lame_close.argtypes = (Lib.lame_t, )
        self.lame_close.restype = None

        self.lame_set_write_id3tag_automatic.argtypes = (Lib.lame_t, c_int)
        self.lame_set_write_id3tag_automatic.restype = None

        self.lame_get_write_id3tag_automatic.argtypes = (Lib.lame_t,)
        self.lame_get_write_id3tag_automatic.restype = c_int

libmp3lame = Lib()

class Lame:
    def __init__(self, **kwargs):
        self.lame = libmp3lame.lame_init()
        for k, v in kwargs.items():
            setattr(self, k, v)

        self._max_encode_samples = 131072
        self._write_buf_len = self._max_encode_samples * 5//4 + 7200
        self._max_encode_samples = 15
        self._write_buf = cast(create_string_buffer(self._write_buf_len), POINTER(c_byte))


    def __del__(self, **kwargs):
        libmp3lame.lame_close(self.lame)


    @property
    def num_samples(self) -> c_ulong:
        """
        number of samples.  default = 2^32-1
        """
        return libmp3lame.lame_get_num_samples(self.lame)
    @num_samples.setter
    def num_samples(self, value: c_ulong):
        return libmp3lame.lame_set_num_samples(self.lame, value)


    @property
    def in_samplerate(self) -> c_ulong:
        """
        input sample rate in Hz.  default = 44100hz
        """
        return libmp3lame.lame_get_in_samplerate(self.lame)
    @in_samplerate.setter
    def in_samplerate(self, value: c_ulong):
        return libmp3lame.lame_set_in_samplerate(self.lame, value)


    @property
    def num_channels(self) -> c_int:
        """
        number of channels in input stream. default=2
        """
        return libmp3lame.lame_get_num_channels(self.lame)
    @num_channels.setter
    def num_channels(self, value: c_int):
        return libmp3lame.lame_set_num_channels(self.lame, value)


    @property
    def scale(self) -> c_float:
        """
        scale the input by this amount before encoding.  default=1
        (not used by decoding routines)
        """
        return libmp3lame.lame_get_scale(self.lame)
    @scale.setter
    def scale(self, value: c_float):
        return libmp3lame.lame_set_scale(self.lame, value)


    @property
    def scale_left(self) -> c_float:
        """
        scale the channel 0 (left) input by this amount before encoding.  default=1
        (not used by decoding routines)
        """
        return libmp3lame.lame_get_scale_left(self.lame)
    @scale_left.setter
    def scale_left(self, value: c_float):
        return libmp3lame.lame_set_scale_left(self.lame, value)


    @property
    def scale_right(self) -> c_float:
        """
        scale the channel 1 (right) input by this amount before encoding.  default=1
        (not used by decoding routines)
        """
        return libmp3lame.lame_get_scale_right(self.lame)
    @scale_right.setter
    def scale_right(self, value: c_float):
        return libmp3lame.lame_set_scale_right(self.lame, value)


    @property
    def bitrate(self) -> c_int:
        """
        set one of brate compression ratio.  default is compression ratio of 11.
        """
        return libmp3lame.lame_get_brate(self.lame)
    @bitrate.setter
    def bitrate(self, value: c_int):
        libmp3lame.lame_set_compression_ratio(self.lame, 0)
        return libmp3lame.lame_set_brate(self.lame, value)


    @property
    def compression_ratio(self) -> c_float:
        """
        set one of brate compression ratio.  default is compression ratio of 11.
        """
        return libmp3lame.lame_get_compression_ratio(self.lame)
    @compression_ratio.setter
    def compression_ratio(self, value: c_float):
        libmp3lame.lame_set_brate(self.lame, 0)
        return libmp3lame.lame_set_compression_ratio(self.lame, value)


    @property
    def mode(self) -> MpegMode:
        """
        mode = 0,1,2,3 = stereo, jstereo, dual channel (not supported), mono
        default: lame picks based on compression ration and input channels
        """
        return MpegMode(libmp3lame.lame_get_mode(self.lame))
    @mode.setter
    def mode(self, value: MpegMode):
        return libmp3lame.lame_set_mode(self.lame, value.value)


    @property
    def quality(self) -> c_int:
        """
        internal algorithm selection.  True quality is determined by the bitrate
        but this variable will effect quality by selecting expensive or cheap algorithms.
        quality=0..9.  0=best (very slow).  9=worst.
        recommended:  2     near-best quality, not too slow
                      5     good quality, fast
                      7     ok quality, really fast
        """
        return libmp3lame.lame_get_quality(self.lame)
    @quality.setter
    def quality(self, value: c_int):
        return libmp3lame.lame_set_quality(self.lame, value)



    @property
    def write_id3tag_automatic(self) -> bool:
        """
        normaly lame_init_param writes ID3v2 tags into the audio stream
        Call lame_set_write_id3tag_automatic(gfp, 0) before lame_init_param
        to turn off this behaviour and get ID3v2 tag with above function
        write it yourself into your file.
        """
        return bool(libmp3lame.lame_get_write_id3tag_automatic(self.lame))
    @write_id3tag_automatic.setter
    def write_id3tag_automatic(self, value: bool):
        return libmp3lame.lame_set_write_id3tag_automatic(self.lame, 1 if value else 0)


    def init_params(self):
        """
        REQUIRED:
        sets more internal configuration based on data provided above.
        returns -1 if something failed.
        """
        return libmp3lame.lame_init_params(self.lame)


    def encode_buffer(self, buffer: np.ndarray) -> bytes:
        num_samples = len(buffer) // 2
        buffer_ptr = buffer.ctypes.data_as(POINTER(c_short))
        ret = b''
        for slice_start in range(0, num_samples, self._max_encode_samples):
            slice_ptr = cast(addressof(buffer_ptr.contents)+2*slice_start*sizeof(c_short), POINTER(c_short))
            slice_len = min(num_samples-slice_start, self._max_encode_samples)

            n = libmp3lame.lame_encode_buffer_interleaved(
                    self.lame,
                    slice_ptr, slice_len,
                    self._write_buf,
                    self._write_buf_len)
            if n != 0:
                chunk = string_at(self._write_buf, n)
                ret = ret + chunk if ret is not None else chunk
        return ret if ret is not None else b''


    def encode_flush(self, nogap: bool = False) -> bytes:
        """
        REQUIRED:
        lame_encode_flush will flush the intenal PCM buffers, padding with
        0's to make sure the final frame is complete, and then flush
        the internal MP3 buffers, and thus may return a
        final few mp3 frames.  'mp3buf' should be at least 7200 bytes long
        to hold all possible emitted data.

        will also write id3v1 tags (if any) into the bitstream
        """
        n = libmp3lame.lame_encode_flush(self.lame, self._write_buf, self._write_buf_len)
        return string_at(self._write_buf, n)


    def encode_flush_nogap(self) -> bytes:
        """
        OPTIONAL:
        lame_encode_flush_nogap will flush the internal mp3 buffers and pad
        the last frame with ancillary data so it is a complete mp3 frame.

        'mp3buf' should be at least 7200 bytes long
        to hold all possible emitted data.

        After a call to this routine, the outputed mp3 data is complete, but
        you may continue to encode new PCM samples and write future mp3 data
        to a different file.  The two mp3 files will play back with no gaps
        if they are concatenated together.

        This routine will NOT write id3v1 tags into the bitstream.
        """
        n = libmp3lame.lame_encode_flush_nogap(self.lame, cast(self._write_buf, POINTER(c_byte)), self._write_buf_len)
        return string_at(self._write_buf, n)


if __name__ == '__main__':
    encoder = Lame(num_samples=12, in_samplerate=44100, num_channels=2, scale=1.1, scale_left=.95, scale_right=.93, write_id3tag_automatic=True, compression_ratio=5, bitrate=500, quality=5)
    print(encoder.num_samples, encoder.in_samplerate, encoder.num_channels, encoder.scale, encoder.scale_left, encoder.scale_right, encoder.write_id3tag_automatic, encoder.bitrate, encoder.compression_ratio, encoder.mode, encoder.quality)

    encoder.init_params()
    import math

    freq1 = 440
    freq2 = 880
    sample_rate = 44100
    chunk_len = 44100 // 440
    chunk = np.array([
        [30000 * math.cos(i*2*math.pi*freq1/sample_rate) for i in range(chunk_len)],
        [ 5000 * math.sin(i*2*math.pi*freq2/sample_rate) for i in range(chunk_len)],
    ], np.int16).reshape([-1], order='F')

    with open('foo.mp3', 'wb') as f:
        for i in range(3000):
            f.write(encoder.encode_buffer(chunk))
        f.write(encoder.encode_flush_nogap())
