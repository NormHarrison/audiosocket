# Import the audiosocket module
from audiosocket import audiosocket


# Create a new Audiosocket server instance, passing it binding
# information in a tuple just as you would a standard Python socket.
as_server = audiosocket.AudioSocketServer(("0.0.0.0", 1234))


# Tell the server to start listening to connection. Two optional parameters
# are accepted:
#
#   'backlog': Which specifies how many inbound connections can be queued
#    until they start being denied (passed to the underlying socket module).
#
#   'timeout': Which sets a time limit on the server's socket operations,
#    preventing the 'accept()' method from blocking indefinitely.

as_server.listen()


# This will block until a connection is received, returning
# an 'AudioSocketConnection' instance once one arrives.
call = as_server.accept()


print('Received connection from {0}'.format(call.peer_name[0]))
print("UUID of call is: " + call.uuid)


# While a connection to the remote channel exists, send all
# received audio back to Asterisk (creates an echo).
while call.connected:
  audio_data = call.read()
  call.write(audio_data)


call.hangup()
as_server.close()

print('Connection with {0} over'.format(call.peer_name[0]))
