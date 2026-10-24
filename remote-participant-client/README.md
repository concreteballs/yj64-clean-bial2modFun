# YJ-64 Remote Participant — client

A small cross-platform command-line client for joining the YJ-64 remote chat from Bogdan's computer.

## Requirements
- Python 3.10 or newer
- Network access to the YJ-64 relay
- A relay URL and participant token supplied by the YJ-64 administrator

The client relays text chat only. It does not run commands on the computer, expose files, or grant remote desktop access.

## Windows setup
1. Install Python 3.10+ from https://www.python.org/downloads/ and enable **Add Python to PATH**.
2. Extract this folder somewhere writable.
3. Open Command Prompt in this folder.
4. Run:
   \`py -m pip install -r requirements.txt\`
5. Start the client:
   \`py yj64_remote_participant.py\`
6. Enter the relay URL, participant name, and token when prompted. Token input is hidden.
7. Type a message and press Enter. Type \`/quit\` to disconnect.

## Linux / macOS setup
In a terminal in this folder:
\`\`\`sh
python3 -m pip install -r requirements.txt
python3 yj64_remote_participant.py
\`\`\`

## Optional command-line settings
\`\`\`sh
python yj64_remote_participant.py --url wss://relay.example:8765 --name Bogdan
\`\`\`
The token is still requested securely unless the environment variable named by \`--token-env\` is set. Avoid putting tokens in command-line arguments or sharing them in chat.

## Security
- Remote connections must use \`wss://\` with a valid TLS certificate.
- Plain \`ws://\` is accepted only for loopback addresses on the same computer.
- Do not commit, email, or paste the participant token into public issues.
- The server must be running and configured with the matching token before this client can connect.

## Current deployment status
This package is the client only. It does **not** include a public server address or token. The administrator must deploy the relay and provide Bogdan with the final \`wss://\` URL and a private token before a live connection can be tested.
