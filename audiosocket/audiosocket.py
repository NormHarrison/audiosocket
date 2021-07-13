import socket
import audioop
import time

from enum import IntEnum


# Find length of uncompressed audio:
# (8 * <number_of_bytes>) / (<sample_rate> * <bit_depth> * <channel_count>)


# Acceptable values for the "encoding" parameter of the
# "ResampleConfig" class.
ENCODING_NONE = 0
ENCODING_ULAW = 1
ENCODING_ALAW = 2


# The expected size of an AudioSocket message header in bytes.
_HEADER_SIZE = 3


# The various payload types that AudioSocket uses.
class _PayloadTypes(IntEnum):
  HANGUP  = 0x00
  UUID    = 0x01
  SILENCE = 0x02
  AUDIO   = 0x10
  ERROR   = 0xff


# The various error codes that can occur on the Asterisk server's end.
class _ErrorCodes(IntEnum):
  NONE   = 0x00
  HANGUP = 0x01
  FRAME  = 0x02
  MEMORY = 0x04


class _AudioSocketError(Exception):
  pass


class BadHeaderError(_AudioSocketError):

  def __init__(self, peer_addr, msg):
    super().__init__("Header received from the peer \"{0}\": {1}".format
    (peer_addr, msg))


class _AsteriskError(Exception):

  def __init__(self, peer_addr, msg):
    super().__init__("The Asterisk instance located at \"{0}\" ".format
    (peer_addr) + msg)


class UnknownError(_AsteriskError):

  def __init__(self, peer_addr, code):

    super().__init__(peer_addr, "sent an unknown error code: \"{0}\"".format
    (code))


class AbsentError(_AsteriskError):  # What does this actually mean?

  def __init__(self, peer_addr):

    super().__init__(peer_addr, "indicated no error was present.")


class HangupError(_AsteriskError):

  def __init__(self, peer_addr):

    super().__init__(peer_addr, "indicated the connected channel hung up")


class FrameError(_AsteriskError):

  def __init__(self, peer_addr):

    super().__init__(peer_addr, "indicated an audio frame couldn't be sent")


class MemoryError(_AsteriskError):

  def __init__(self, peer_addr):

    super().__init__(peer_addr, "indicated a memory related error occurred")


# Represents a configuration for resampling audio
class ResampleConfig:

  def __init__(self, rate, channels, encoding=ENCODING_NONE):

    self._rate           = rate
    self._resample_state = None
    self._channels       = channels
    self._encoding       = encoding


# Represents an individual AudioSocket connection with an Asterisk channel.
class _AudioSocketConnection:

  def __init__(self, new_conn):

    self._conn_sock      = new_conn[0]
    self._next_send_time = 0

    self._resample_read_config  = None
    self._resample_write_config = None

    self.peer_name = new_conn[1]
    self.uuid      = ""
    self.connected = True

    self.uuid = self._read_message(_PayloadTypes.UUID).hex()


  def set_resample_read_config(self, config):

    self._resample_read_config = config


  def set_resample_write_config(self, config):

    self._resample_write_config = config


  def _decode_and_raise_error(self, code):

    self.connected = False

    if code == _ErrorCodes.NONE:
      raise AbsentError(self.peer_name[0])

    elif code == _ErrorCodes.HANGUP:
      raise HangupError(self.peer_name[0])

    elif code == _ErrorCodes.FRAME:
      raise FrameError(self.peer_name[0])

    elif code == _ErrorCodes.MEMORY:
      raise MemoryError(self.peer_name[0])

    else:
      raise UnknownError(self.peer_name[0], code)


  def _resample_write(self, audio_data):

    if self._resample_write_config._encoding == ENCODING_ULAW:
      audio_data = audioop.ulaw2lin(audio_data, 2)

    elif self._resample_write_config._encoding == ENCODING_ALAW:
      audio_data = audioop.alaw2lin(audio_data, 2)


    if self._resample_write_config._channels == 1:
      audio_data = audioop.tomono(audio_data, 2, 1, 1)


    if self._resample_write_config._rate != 8000:

      resample_tuple = audioop.ratecv(
        fragment  = audio_data,
        width     = 2,
        nchannels = 1,
        inrate    = self._resample_write_config._rate,
        outrate   = 8000,
        state     = self._resample_write_config.resample_state
      )

      audio_data                                 = resample_tuple[0]
      self._resample_write_config.resample_state = resample_tuple[1]

    return audio_data


  def _write_message(self, payload_type, payload):

    payload_length = len(payload).to_bytes(length=2, byteorder="big")
    b_payload_type = payload_type.to_bytes(length=1, byteorder="big")

    current_time = time.time()

    if current_time < self._next_send_time:
      time.sleep(self._next_send_time - current_time)

    duration = (8 * len(payload)) / (8000 * 16 * 1)
    self._next_send_time = time.time() + duration

    # Keep experimenting?: time.sleep(0.020)

    try:
      self._conn_sock.sendall(b_payload_type + payload_length + payload)
    except (BrokenPipeError, ConnectionResetError):
      self.connected = False


  def write(self, audio_data):

    if not self.connected:
      return

    byte_count = len(audio_data)

    if byte_count > 65535:
      raise AudioSocketError("Payload cannot be larger than 65535 bytes")

    start_index = 0
    end_index   = 320

    while True:

      if self._resample_write_config != None:
        audio_data = self._resample_write(audio_data)

      self._write_message(
        _PayloadTypes.AUDIO,
        audio_data[start_index:end_index]
      )

      if end_index >= byte_count:
        break

      start_index  = end_index
      end_index   += end_index


  def _resample_read(self, audio_data):

    if self._resample_read_config._encoding == ENCODING_ULAW:
      audio_data = audioop.ulaw2lin(audio_data, 2)

    elif self._resample_read_config._encoding == ENCODING_ALAW:
      audio_data = audioop.alaw2lin(audio_data, 2)


    if self._resample_read_config._channels == 2:
      audio_data = audioop.tostereo(audio_data, 2, 1, 1)


    if self._resample_read_config._rate != 8000:

      resample_tuple = audioop.ratecv(
        fragment  = audio_data,
        width     = 2,
        nchannels = 1,
        inrate    = 8000,
        outrate   = self._resample_read_config._rate,
        state     = self._resample_read_config.resample_state
      )

      audio_data                                = resample_tuple[0]
      self._resample_read_config.resample_state = resample_tuple[1]

    return audio_data


  def _read_message(self, expected_type):

    # !!! Add a timeout to combat malicious clients

    try:
      header_only = self._conn_sock.recv(_HEADER_SIZE)
    except (BrokenPipeError, ConnectionResetError):
      self.connected = False
      return b""

    if len(header_only) != _HEADER_SIZE:
      self.connected = False
      return b""

    for type in _PayloadTypes:

      if header_only[0] == type:
        valid_type = True
        break

      valid_type = False

    if not valid_type:
      self.connected = False
      raise BadHeaderError(self.peer_name[0], "didn't contain a valid type")

    payload_type   = header_only[0]
    payload_length = int.from_bytes(header_only[1:], byteorder="big")

    if payload_type != expected_type:

      if payload_type == _PayloadTypes.ERROR:
        self._decode_and_raise_error (payload)

      else:
        raise AudioSocketError("Expected to receive a message of type "
        + "{0} from the peer {1}, but got {2}".format
        (expected_type, self.peer_name[0], payload_type))

    payload = self._conn_sock.recv(payload_length)

    while len(payload) != payload_length:
      payload += self._conn_sock.recv(payload_length - len(payload))

    return payload


  def read(self):

    audio_data = self._read_message(_PayloadTypes.AUDIO)

    if self._resample_read_config != None:
      return self._resample_read(audio_data)

    else
      return audio_data


  def hangup(self):

    if not self.connected:
      return

    self._write_message(_PayloadTypes.HANGUP, b"")
    self._conn_sock.close()
    self.connected = False


# Represents an AudioSocket server, which returns
# "AudioSocketConnection" instances.

class AudioSocketServer:

  def __init__(self, bind_info):

    if not isinstance(bind_info, tuple):
      raise TypeError("Expected tuple (addr, port), received ",
      type(bind_info))

    self.listening = False
    self.bind_addr, self.bind_port = bind_info

    self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._server_sock.bind((self.bind_addr, self.bind_port))

    # If the user let the operating system choose a port (by passing in 0), then
    # the one it selected is available in this attribute
    self.bind_port = self._server_sock.getsockname()[1]


  def listen(self, backlog = 15, timeout = None):

    self._server_sock.listen(backlog)
    self._server_sock.settimeout(timeout)

    self.listening = True


  def accept(self):

    if not self.listening:
      raise AudioSocketError("'accept()' cannot be called before 'listen()'")

    return _AudioSocketConnection (self._server_sock.accept())


  def close(self):

    if not self.listening:
      return

    self._server_sock.close()
    self.listening = False
