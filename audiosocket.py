# Standard Python modules
import socket
from threading import Thread
from dataclasses import dataclass
from time import sleep

# Audisocket connection class
from connection import *



# Generic dataclass used by both the prepare_input and prepare_output methods
# for passing around audio resampling information
@dataclass
class audioop_struct:
  ratecv_state: None
  rate: int
  channels: int
  ulaw2lin: bool



# Creates a new audiosocket object
class Audiosocket:
  def __init__(self, bind_info, timeout=None):

    # By default, features of audioop (for example: resampling
    # or re-mixng input/output) are disabled
    self.user_resample = None
    self.asterisk_resample = None


    if not isinstance(bind_info, tuple):
      raise TypeError("Expected tuple (addr, port), received", type(bind_info))


    self.addr, self.port = bind_info

    self.initial_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.initial_sock.bind((self.addr, self.port))
    self.initial_sock.settimeout(timeout)
    self.initial_sock.listen(3)

    # If the user let the operating system choose a port (by passing in 0), then
    # the one it selected is available in this attribute
    self.port = self.initial_sock.getsockname()[1]



  # Optionally prepares audio sent by the user to
  # the specifications needed by audiosocket (16-bit, 8KHz mono LE PCM).
  # Audio sent in must be in PCM or ULAW format
  def prepare_input(self, rate=44000, channels=2, ulaw2lin=False):
    self.user_resample = audioop_struct(
      rate = rate,
      channels = channels,
      ulaw2lin = ulaw2lin,
      ratecv_state = None,
    )



  # Optionally prepares audio sent by audiosocket to
  # the specifications of the user
  def prepare_output(self, rate=44000, channels=1, ulaw2lin=False):
    self.asterisk_resample = audioop_struct(
      rate = rate,
      channels = channels,
      ulaw2lin = ulaw2lin,
      ratecv_state = None,
    )



  def listen(self):
    conn_sock, peer_addr = self.initial_sock.accept()
    call_conn = Connection(
      conn_sock,
      peer_addr,
      self.user_resample,
      self.asterisk_resample,
    )

    call_conn_thread = Thread(target=call_conn._process)
    call_conn_thread.start()

    return call_conn
