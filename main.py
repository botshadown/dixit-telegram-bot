from telegram.ext import (Updater, CommandHandler, InlineQueryHandler,
                          MessageHandler, Filters)
import logging
from game import DixitGame
from utils import *

'''
TODO

[ ] HIDE CARD ID. Even if we use blank-character wizardry, we should change the
    ID of the card between when the storyteller and other players play the card
    and when the other players choose.

[ ] End game
    [ ] Implement criterion to end the game
    [ ] Improve the way results are shown; one of the fun parts of dixit is
        discussing whose answer each person has chosen
        [X] Temporarily, show via text who voted on whose card
    [X] Allow new players to join the game between rounds
    [X] Show total and last round's points

[X] Force InlineQuery to discard its cache and update itself even on empty
    queries

[ ] Confirm that the player's chosen cards were available for choosing, at every
    stage?

[X] Show user buttons to direct him to his cards automatically (vide Uno_Bot)

[ ] Have the bot reply to the relevant message, instead of sending simple
    messages, when appropriate

[ ] Debugging
    [ ] Have dummy players to better debug the game alone. They would not be
        storytellers, but could just always choose a random card when
        playing/voting.
    [X] Define custom Exceptions?
    [ ] Create unit tests

[ ] Localization
    [ ] Store display messages in an external file
    [ ] Implement ability to translate to other languages. Test with pt-BR

'''

@ensure_game(exists=False)
@ensure_user_inactive
def new_game_callback(update, context):
    '''Runs when /newgame is called. Creates an empty game and adds the master'''
    user = update.message.from_user

    logging.info("NEW GAME")
    logging.info("We're now at stage 0: Lobby!")

    dixit_game = DixitGame.new_game(master=user)
    context.chat_data['dixit_game'] = dixit_game

    send_message(f"Let's play Dixit!\nThe master {dixit_game.master} "
                  "has created a new game. \nClick /joingame to join and "
                  "/startgame to start playing!",
                  update, context)


@ensure_game(exists=True)
@ensure_user_inactive
@handle_exceptions(TooManyPlayersError, UserAlreadyInGameError)
def join_game_callback(update, context):
    '''Runs when /joingame is called. Adds the user to the game'''
    dixit_game = context.chat_data['dixit_game']
    user = update.message.from_user
    logging.info(f'{user.first_name=}, {user.id=} joined the game')

    dixit_game.add_player(user)
    if dixit_game.stage==0:
        text = f"{user.first_name} was added to the game!"
    else:
        text = f"Welcome {user.first_name}! You may start playing when a new "\
                "rounds begins"
    send_message(text, update, context)


@ensure_game(exists=True)
@handle_exceptions(HandError, UserIsNotMasterError, GameAlreadyStartedError)
def start_game_callback(update, context):
    '''Runs when /startgame is called. Does the final preparations for the game'''
    dixit_game = context.chat_data['dixit_game']
    user = update.message.from_user
    dixit_game.start_game(user) # can no longer log the chosen cards!
    send_message(f"The game has begun!", update, context)
    storytellers_turn(update, context)


def storytellers_turn(update, context):
    '''Instructs the storyteller to choose a clue and a card'''
    dixit_game = context.chat_data['dixit_game']
    logging.info("We're now at stage 1: Storyteller's turn!")
    send_message(f'{dixit_game.storyteller} is the storyteller!\n'
                 'Please write a clue and click on a card.', update, context,
                 button='Click to see your cards!')


def inline_callback(update, context):
    '''Decides what cards to show when a player makes an inline query'''
    user = update.inline_query.from_user
    [dixit_game] = find_user_games(context, user).values()
    [player] = [p for p in dixit_game.players if p.user == user]
    storyteller = dixit_game.storyteller
    table = dixit_game.table

    logging.info(f'Inline from {player!r}')
    logging.info(f'Player is {"not " * (player!=storyteller)}the storyteller')

    text = clue = None
    if dixit_game.stage == 1 and player == storyteller:
        clue = update.inline_query.query
        cards = player.hand
    elif dixit_game.stage == 2 and player != storyteller:
        cards = player.hand
    elif dixit_game.stage == 3 and player != storyteller:
        cards = table.values()
    else:
        cards = table.values() if dixit_game.stage==3 else player.hand
        text = f'{player} is impatient...'

    results = [menu_card(card, player, text, clue) for card in cards]
    update.inline_query.answer(results, cache_time=0)


def parse_cards(update, context):
    '''Parses the user messages and retrieves the player and the played card'''
    dixit_game = context.chat_data['dixit_game']
    user = update.message.from_user
    text = update.message.text

    data, *clue = text.split('\n', maxsplit=1)
    user_id, card_id = (int(i) for i in data.split(':'))
    logging.info(f'Parsing {user_id=}, {card_id=}, {user.first_name=}, '
                 f'{user.id=}')
    try:
        [player] = [p for p in dixit_game.players if p.id == user_id]
    except ValueError:
        send_message(f'You, {user.first_name}, are not playing the game!',
                     update, context)
        return

    try:
        [card_sent] = [c for c in dixit_game.cards if c.id == card_id]
    except ValueError:
        send_message(f"This card doesn't exist, {player}!", update, context)
        return

    if dixit_game.stage == 1:
        assert player == dixit_game.storyteller, "Player is not the storyteller"

        if len(clue) != 1:
            send_message(f'You forgot to give us a clue!', update, context)
            return
        [clue] = clue
        logging.info(f'{clue=}')
        logging.info("We're now at stage 2: others' turn!")

        dixit_game.storyteller_turn(card=card_sent, clue=clue)

        send_message(f"Now, let the others send their cards!\n"
                     f"Clue: *{dixit_game.clue}*", update, context,
                     button='Click to see your cards!',
                     parse_mode='Markdown')

    elif dixit_game.stage == 2:
        dixit_game.player_turns(player=player, card=card_sent)

        logging.info(f"There are ({len(dixit_game.table)}/"
                     f"{len(dixit_game.players)}) cards on the table!")
        if dixit_game.stage == 3:
            logging.info("We're now at stage 3: vote!")

            send_message(f"Hear ye, hear ye! Time to vote!\n"
                         f"Clue: *{dixit_game.clue}*", update, context,
                         button='Click to see the table!',
                         parse_mode='Markdown')

    elif dixit_game.stage == 3:
        try:
            [sender] = [p for p in dixit_game.players
                        if dixit_game.table[p]==card_sent]
        except:
            send_message('This card belongs to no one, {player}!')

        dixit_game.voting_turns(player=player, vote=sender)

        logging.info(f"I've received ({len(dixit_game.votes)}/"
                     f"{len(dixit_game.players) - 1}) votes")
        if len(dixit_game.votes) == len(dixit_game.players)-1:
            dixit_game.end_of_round()
            end_of_round(update, context)


def end_of_round(update, context):
    '''Counts points, resets the appropriate variables for the next round'''
    dixit_game = context.chat_data['dixit_game']

    storyteller_card = dixit_game.table[dixit_game.storyteller]

    send_message(f'The correct answer was...', update, context)
    send_photo(storyteller_card.url, update, context)

    results = '\n'.join([f'{player.name}:  {Pts} ' + f'(+{pts})'*(pts!=0)
                         for player, (Pts, pts) in dixit_game.score.items()])

    vote_list = []
    grouped_votes = {}
    for voter, voted in dixit_game.votes.items():
        grouped_votes.setdefault(voted, []).append(voter)
    for voted, voters in grouped_votes.items():
       vote_list.append(f'{voters[0]} \u27f6 {voted}') # bash can't handle char
       for voter in voters[1:]:
           vote_list.append(str(voter))
       vote_list.append('')
    votes = '\n'.join(vote_list)

    send_message(results, update, context)
    send_message(votes, update, context)

    dixit_game.new_round()
    storytellers_turn(update, context)


def run_bot(token):
    '''Tells the bot to use the functions we've defined, starts the main loop'''
    updater = Updater(token, use_context=True)
    dispatcher = updater.dispatcher

    # Add commands handlers
    command_callbacks = {'newgame': new_game_callback,
                         'joingame': join_game_callback,
                         'startgame': start_game_callback}
    for name, callback in command_callbacks.items():
        dispatcher.add_handler(CommandHandler(name, callback))

    # Add inline handler
    inline_handler = InlineQueryHandler(inline_callback)
    dispatcher.add_handler(inline_handler)

    # Add messages handler, to parse the card ids sent by the player
    pattern = r'^\d+:\d+(?:\n.*)?$'
    message_handler = MessageHandler(Filters.regex(pattern), parse_cards)
    # I don't know why, but Filter.via_bot() isn't letting it pass...
    dispatcher.add_handler(message_handler)

    # Start the bot
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    logging_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(format=logging_format, level=logging.INFO)
    with open('token.txt', 'r') as token_file:
        token = token_file.readline().strip() # Remove \n at the end
    run_bot(token)
