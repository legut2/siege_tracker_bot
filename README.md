# siege_tracker_bot
Discord bot to keep track of competition between friends within R6.

Python 3.10.0
`python -m venv venv`
`.\venv\Scripts\activate`
`pip install -U discord.py`

Usage
`
/tracker start player1:<name> player2:<name> → posts the tracker with buttons.
`
`
/tracker play player:<P1 or P2> operator:<name> → marks that operator as played (autocomplete shows remaining).
`

Server Setup
$env:PATH = "$env:USERPROFILE\.fly\bin;$env:PATH"
flyctl --version
flyctl auth login