# Standard Python modules
import audioop
from queue import Queue, Empty
from dataclasses import dataclass
from threading import Lock
from time import sleep


class AsteriskError(Exception):

  def __init__(self, message):
    super().__init__(message)


# A sort of imitation struct that holds all of the possible
# AudioSocket message types

@dataclass(frozen=True)
class types_struct:
  uuid:    bytes = b'\x01'   # Message payload contains UUID set in Asterisk Dialplan
  audio:   bytes = b'\x10'   # * Message payload contains 8Khz 16-bit mono LE PCM audio (* See Github readme)
  silence: bytes = b'\x02'   # Message payload contains silence (I've never seen this occur personally)
  hangup:  bytes = b'\x00'   # Tell Asterisk to hangup the call (This doesn't appear to ever be sent from Asterisk to us)
  error:   bytes = b'\xff'   # Message payload contains an error from Asterisk

types = types_struct()


# The size of 20ms of 8KHz 16-bit mono LE PCM represented as a
# 16 bit (2 byte, size of length header) unsigned BE integer

# This amount of the audio data mentioned above is equal
# to 320 bytes, which is the required payload size when
# sending audio back to AudioSocket for playback on the
# bridged channel. Sending more or less data will result in distorted sound
PCM_SIZE = (320).to_bytes(2, 'big')


# Similar to one above, this holds all the possible
# AudioSocket related error codes Asterisk can send us

@dataclass(frozen=True)
class errors_struct:
  none:   bytes = b'\x00'
  hangup: bytes = b'\x01'
  frame:  bytes = b'\x02'
  memory: bytes = b'\x04'

errors = errors_struct()


class Connection:

  def __init__(self, conn_sock, peer_addr, user_resample, asterisk_resample):

    self.conn_sock = conn_sock
    self.peer_addr = peer_addr
    self.uuid = None
    self.connected = True
    self._user_resample = user_resample
    self._asterisk_resample = asterisk_resample

    # Underlying Queue instances for passing incoming/outgoing audio between threads
    self._rx_q = Queue(500)
    self._tx_q = Queue(500)
  
    self._lock = Lock()


  # Splits data sent by AudioSocket into three different peices
  def _split_data(self, data):

    if len(data) < 3:
      raise AsteriskError('Audiosocket message from Asterisk was corrupted (less than 3 bytes)')

    else:
           # type      length                            payload
      return data[:1], int.from_bytes(data[1:3], 'big'), data[3:]



  # If the type of message received was an error, this
  # prints an explanation of the specific one that occurred
  def _decode_error(self, payload):
    if payload == errors.none:
      raise AsteriskError('Unknown error code')

    elif payload == errors.hangup:
      raise AsteriskError('The called party hung up')

    elif payload == errors.frame:
      raise AsteriskError('Failed to send audio frame to Audiosocket server')

    elif payload == errors.memory:
      raise AsteriskError('Memory allocation error')

    return



  # Gets AudioSocket audio from the rx queue
  def read(self):

    try:
      audio_data = self._rx_q.get(timeout=0.2)

    except Empty:
      return bytes(320)

    if self._asterisk_resample:
      # If AudioSocket is bridged with a channel
      # using the ULAW audio codec, the user can specify
      # to have it converted to linear PCM encoding upon reading.
      if self._asterisk_resample.ulaw2lin:
        audio_data = audioop.ulaw2lin(audio_data, 2)

      # If the user chose a sample rate different
      # from the default, then resample the audio to the rate they specified
      if self._asterisk_resample.rate != 8000:
        audio_data, self._asterisk_resample.ratecv_state = audioop.ratecv(
          audio_data,
          2,
          1,
          8000,
          self._asterisk_resample.rate,
          self._asterisk_resample.ratecv_state,
        )

      # If the user requested the output be in stereo,
      # then convert it from mono
      if self._asterisk_resample.channels == 2:
        audio_data = audioop.tostereo(audio_data, 2, 1, 1)

    return audio_data



  # Puts user supplied audio into the tx queue
  def write(self, audio_data):

    if self._user_resample:
      # The user can also specify to have ULAW encoded source audio
      # converted to linear PCM encoding upon being written.
      if self._user_resample.ulaw2lin:
        # Possibly skip downsampling if this was triggered, as
        # while ULAW encoded audio can be sampled at rates other
        # than 8KHz, since this is telephony related, it's unlikely.
        audio_data = audioop.ulaw2lin(audio_data, 2)

      # If the audio isn't already sampled at 8KHz,
      # then it needs to be downsampled first
      if self._user_resample.rate != 8000:
        audio_data, self._user_resample.ratecv_state = audioop.ratecv(
          audio_data,
          2,
          self._user_resample.channels,
          self._user_resample.rate,
          8000,
          self._user_resample.ratecv_state,
        )

      # If the audio isn't already in mono, then
      # it needs to be downmixed as well
      if self._user_resample.channels == 2:
        audio_data = audioop.tomono(audio_data, 2, 1, 1)

    self._tx_q.put(audio_data)


  # Tells Asterisk to hangup the call from it's end.
  # Although after the call is hungup, the socket on Asterisk's end
  # closes the connection via an abrupt RST packet, resulting in a "Connection reset by peer"
  # error on our end. Unfortunately, using try and except around self.conn_sock.recv() is as 
  # clean as I think it can be right now
  def hangup(self):

    # Three null bytes indicate a hangup message
    with self._lock:
      self.conn_sock.send(types.hangup * 3)

    sleep(0.2)
    return



  def _process(self):

    # The main audio receiving/sending loop, this loops
    # until AudioSocket stops sending us data, the hangup() method is called or an error occurs.
    # A disconnection can be triggered from the users end by calling the hangup() method
    while True:

      data = None

      try:
        with self._lock:
          data = self.conn_sock.recv(323)

      except ConnectionResetError:
        pass


      if not data:
        self.connected = False
        self.conn_sock.close()
        return


      type, length, payload = self._split_data(data)


      if type == types.audio:

        # Adds received audio into the rx queue
        self._rx_q.put(payload)

        # To prevent the tx queue from blocking all execution if
        # the user doesn't supply it with (enough) audio, null bytes (silence)
        # are generated manually and sent back to Asterisk whenever its empty.
        if self._tx_q.empty():
          self.conn_sock.send(types.audio + PCM_SIZE + bytes(320))

        else:
          # If a chunk of audio data in the tx queue is larger than
          # 320 bytes, slice it before sending, however...
          # If the audio data to send is larger than this, then
          # it's probably in the wrong format to begin with and wont be
          # played back properly even when sliced.
          audio_data = self._tx_q.get()[:320]

          with self._lock:
            self.conn_sock.send(types.audio + len(audio_data).to_bytes(2, 'big') + audio_data)


      elif type == types.error:
        self._decode_error(payload)

      elif type == types.uuid:
        self.uuid = payload.hex()
