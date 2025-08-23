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

Buttons on the message:

P1 +1 / −1, P2 +1 / −1

P1 Penalty −10, P2 Penalty −10 (auto-enable when that player has played all 76 operators)