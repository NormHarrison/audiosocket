# Google STT module
from google.cloud import speech

# Import all definitions from the audiosocket module
from audiosocket import * 



stt_client = speech.SpeechClient()

stt_config = speech.RecognitionConfig(
  encoding            = speech.RecognitionConfig.AudioEncoding.LINEAR16,
  sample_rate_hertz   = 8000,
  audio_channel_count = 1,
  model               = 'phone_call',
  language_code       = 'en-US'
)

stt_streaming_config = speech.StreamingRecognitionConfig(
  config           = stt_config,
  single_utterance = False,
  interim_results  = True
)



audiosocket = Audiosocket(('10.0.0.24', 1234))

# Assumes Audiosocket is used via the Asterisk Dial() application, and
# that the channel its bridged with is using the U-Law audio codec.
# If Google's STT service isn't returning any responses, try commenting this out
audiosocket.prepare_output(rate=8000, channels=1, ulaw2lin=True)

while True:
  print('Listening for Audiosocket connections')
  call_conn = audiosocket.listen()
  print('Audiosocket connection received')

  """ This is a generator function (indicated by usage of the keyword "yield"),
  it is a shortcut for making a custom iteraable.

  We need this because the "requests" argument of the "streaming_recognize()"
  method of the "SpeechClient" class expects an iterable that yields bytes """

  def audio_generator():
    while call_conn.connected:
      yield call_conn.read()

  requests = (
    speech.StreamingRecognizeRequest(audio_content=content) for content in audio_generator()
  )

  responses = stt_client.streaming_recognize(stt_streaming_config, requests)

  for response in responses:
    print(response)
