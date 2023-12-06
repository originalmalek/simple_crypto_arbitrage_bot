import os
import traceback
import logging
import telebot
import smtplib

from ybapi import yobit as yobit_api
from binance import client
from dotenv import load_dotenv
from time import sleep, time

logger = logging.getLogger('My logger')

load_dotenv()

first_coin = os.getenv('COIN1')
second_coin = os.getenv('COIN2')
difference = float(os.getenv('PROFIT'))
yobit_api_key = os.getenv('YOBIT_API_KEY')
yobit_api_secret = os.getenv('YOBIT_API_SECRET')
telegram_access_token = os.getenv('TELEGRAM_ACCESS_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
binance_api_secret = os.getenv('BINANCE_API_SECRET')
binance_api_key = os.getenv('BINANCE_API_KEY')
gmail_user = os.getenv('GMAIL_USER')
gmail_password = os.getenv('GMAIL_PASS')

yobit = yobit_api(api_key=yobit_api_key, api_secret=yobit_api_secret)
telebot = telebot.TeleBot(telegram_access_token)
binance = client.Client(api_key=binance_api_key, api_secret=binance_api_secret)


def send_telegram_message(text, chat_id=telegram_chat_id, disable_notification=1):
    try:
        text = f'{coin1}_{coin2}\n' + text
        telebot.send_message(chat_id, text, disable_notification=disable_notification, timeout=0.5)
    except Exception as err:
        logging.error(f"can't' send message  to tg: {err}\n {text}")


def send_email():
    sent_from = gmail_user
    to = ['originalmalek@gmail.com']
    subject = 'Low exchange balance'
    body = "Low exchange balance\n\nUpdate your balance"

    email_text = """\
    From: %s
    To: %s
    Subject: %s

    %s
    """ % (sent_from, ", ".join(to), subject, body)

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.ehlo()
        server.login(gmail_user, gmail_password)
        server.sendmail(sent_from, to, email_text)
        server.close()
    except:
        logger.error(msg="Can't' send email message")
        send_telegram_message("Can't send email")


def check_yobit_error(response):
    if response['success'] == 0:
        logging.error(f'Yobit error:\n{response}')
        send_telegram_message(text=f'Yobit error\n{response}')
        return response['error']
    return False


def cancel_order_yobit(yobit_order_id):
    try:
        response = yobit.cancel_order(yobit_order_id)
    except:
        sleep(3)
        cancel_order_yobit(yobit_order_id)
    is_yobit_error = check_yobit_error(response)
    if is_yobit_error == 'invalid nonce (has already been used)':
        cancel_order_yobit(yobit_order_id)
    if is_yobit_error == '77BFA77E73BE  ':
        cancel_order_yobit(yobit_order_id)
    if is_yobit_error:
        return get_yobit_balance()

    return response['return']['funds_incl_orders'][coin2.lower()]


def cancel_yobit_all_orders():
    response = yobit.active_orders(f'{coin1}_{coin2}')
    if check_yobit_error(response):
        return None

    if 'return' in response:
        for yobit_order_id in response['return']:
            cancel_order_yobit(yobit_order_id)
        send_telegram_message(text='All order canceled')


def get_binance_price():
    try:
        response = float(binance.get_symbol_ticker(symbol=f'{coin1}{"USDT" if coin2 == "USD" else coin2}')['price'])
        return response
    except:
        logging.error('Cant get price on binance')


def count_new_order_amount(yobit_balance, yobit_price):
    # if yobit_balance > 6000:
    #     return (5999 / yobit_price) * 0.9979
    return (yobit_balance / yobit_price) * 0.997999


def create_new_order_yobit(yobit_balance, yobit_price):
    yobit_order_amount = round(count_new_order_amount(yobit_balance, yobit_price), 8)

    response = yobit.trade(f'{coin1}_{coin2}', 'buy', yobit_price, yobit_order_amount)

    if check_yobit_error(response):
        logging.error("Order creation error")
        send_telegram_message(f"{coin1}_{coin2} Order creation error. New attempt in 3 secs.")
        cancel_yobit_all_orders()
        sleep(3)
        yobit_balance = get_yobit_balance()
        binance_last_coin_price = get_binance_price()
        yobit_price = float(binance_last_coin_price) * (1 - profit)
        return create_new_order_yobit(yobit_balance, yobit_price)

    return response['return']['order_id']


def get_yobit_trade_history(timestamp):
    yobit_trade_history = yobit.trade_history(pair=f'{coin1}_{coin2}', since=timestamp)
    if check_yobit_error(yobit_trade_history):
        logging.error("Getting history error")
        send_telegram_message("Getting history error. New attempt in 15 secs.")
        return None

    if 'return' in yobit_trade_history:
        return yobit_trade_history
    return None


def count_yobit_history_trades_amount(yobit_trades_history):
    coin1_orders_amount = 0
    coin2_orders_amount = 0

    for deal in yobit_trades_history['return']:
        if yobit_trades_history['return'][deal]['type'] == 'buy':
            coin1_order_amount = yobit_trades_history['return'][deal]['amount']
            coin2_order_amount = coin1_order_amount * yobit_trades_history['return'][deal]['rate']
            coin1_orders_amount += coin1_order_amount
            coin2_orders_amount += coin2_order_amount

    if coin2_orders_amount >= 11:
        return coin1_orders_amount


def check_new_order(binance_last_coin_price):
    while True:
        sleep(5)
        binance_current_price = get_binance_price()
        max_price_difference = binance_current_price * 0.0003
        if abs(binance_current_price - binance_last_coin_price) >= max_price_difference:
            break
    return binance_current_price


def get_yobit_last_order_timestamp(yobit_trade_history):
    yobit_last_trade_id = max(yobit_trade_history['return'], key=str)
    return int(yobit_trade_history['return'][yobit_last_trade_id]['timestamp'])


def create_binance_new_market_order(timestamp):
    yobit_trades_amount = None
    yobit_trade_history = get_yobit_trade_history(timestamp)

    if yobit_trade_history:
        yobit_trades_amount = count_yobit_history_trades_amount(yobit_trade_history)

    if yobit_trades_amount:
        response = binance.create_order(symbol=f'{coin1}{"USDT" if coin2 == "USD" else coin2}', side='SELL',
                                        quantity=round(yobit_trades_amount, 5), type='MARKET')

        send_telegram_message(text=f"Sold on Binance {response['executedQty']}")
        return get_yobit_last_order_timestamp(yobit_trade_history) + 1
    return timestamp


def get_yobit_balance():
    response = yobit.get_info()
    if check_yobit_error(response):
        get_yobit_balance()
    return response['return']['funds_incl_orders'][coin2.lower()]


def main():
    message_counter = 10
    logger.setLevel('WARNING')
    logging.basicConfig(filename='log.log', level=20)
    cancel_yobit_all_orders()

    timestamp = int(time())
    yobit_balance = get_yobit_balance()
    binance_last_coin_price = get_binance_price()
    yobit_price = float(binance_last_coin_price) * (1 - profit)
    while True:
        try:
            if message_counter == 10:
                message_counter = 0
                send_telegram_message(text=f"YB: {round(yobit_balance)}\n "
                                           f"BLP: {binance_last_coin_price}\n "
                                           f"YLP:{round(yobit_price, 2)}")
            yobit_order_id = create_new_order_yobit(yobit_balance, yobit_price)
            binance_last_coin_price = check_new_order(binance_last_coin_price)
            yobit_balance = round(cancel_order_yobit(yobit_order_id), 2)
            timestamp = create_binance_new_market_order(timestamp)
            yobit_price = float(binance_last_coin_price) * (1 - profit)
            if yobit_balance <= 30:
                send_telegram_message(text=f'Yobit Binance bot stopped.'
                                           f'\nLow balance on Yobit {round(yobit_balance, 2)} USD.',
                                      disable_notification=0)
                send_email()
                break
            message_counter += 1

        except KeyboardInterrupt:
            logging.error('KeyboardInterrupt')
            send_telegram_message(text=f'Exception: KeyboardInterrupt')
            cancel_yobit_all_orders()
            break

        except (ConnectionError, ConnectionResetError):
            logging.error('Connection error.')
            sleep(5)
            cancel_yobit_all_orders()
            send_telegram_message(text=f'Exception: Yobit Binance bot\n{e}\n{traceback_text}')

        except Exception as e:
            cancel_yobit_all_orders()
            yobit_balance = get_yobit_balance()
            binance_last_coin_price = get_binance_price()
            yobit_price = float(binance_last_coin_price) * (1 - profit)

            logging.error(f'Exception. {e}')
            traceback_text = traceback.format_exc()
            send_telegram_message(text=f'Exception: Yobit Binance bot\n{e}\n{traceback_text}\nSleep 15 sec')
            sleep(15)


if __name__ == '__main__':
    coin1 = first_coin
    coin2 = second_coin
    profit = difference  # 0.01 = 1%

    main()
