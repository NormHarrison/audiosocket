# Numpy module, needed for passing audio data to DeepSpeech
import numpy

# Mozilla DeepSpeech module
import deepspeech

# Asterisk audiosocket module
from audiosocket import audiosocket


# Create a DeepSpeech model instance and prepare it for use
dp_model = deepspeech.Model('./deepspeech-0.9.3-models.pbmm')
dp_model.enableExternalScorer('./deepspeech-0.9.3-models.scorer')


# Create a new audisocket server instance
audiosocket = AudiosSocketServer(('0.0.0.0', 1234))

# Since the pretrained DeepSpeech model expects 16000Hz 16-bit, mono PCM audio,
# we need to instruct our audiosocket instance to upsample the incoming
# telephone quality (8000Hz) audio for us, and leave the channel count as is
audiosocket.prepare_output(rate=16000, channels=1)

# Start listening for connections on the audiosocket server
call_conn = audiosocket.listen()
print('Audiosocket connection received from: ', call_conn.peer_addr)


# After a connection has been received, create a new DeepSpeech stream instance from the prepared model for real-time transcription
dp_stream = dp_model.createStream()


# Transcribe for the duration of the phone call
while call_conn.connected:
  # Read audio data from the connected Asterisk channel
  raw_bytes = call_conn.read()

  # DeepSpecch requires that we pass it audio data as a Numpy array holding 16-bit integers.
  # Here, we form the needed type using the raw bytes object returned to us above
  np_audio_array = numpy.frombuffer(raw_bytes, dtype=numpy.int16)

  # Pass the array of audio data to the ongoing DeepSpeech stream, and print the interediate results
  # (this will be blank the first few iterations)
  dp_stream.feedAudioContent(np_audio_array)
  print(dp_stream.intermediateDecode())


# Once the call is over, print out the final transcription
print('Final transcription result:', dp_stream.finishStream())
