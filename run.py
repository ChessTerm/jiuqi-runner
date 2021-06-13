#!/usr/bin/python3

import json
from math import floor
from os import environ
from random import randint
from time import time
from typing import List, Optional

import requests
import stomper
import websocket

from subprocess import Popen, PIPE

API_URL = environ.get('API_URL') or "https://chess.cslab.top/api"
JAR_PATH = environ.get('JAR_PATH') or "./flamechess.jar"

if API_URL:
    while API_URL[-1] == '/':
        API_URL = API_URL[:-1]
WS_URL = f'ws{API_URL[4:]}/ws/no_sockjs'

websocket.enableTrace(True)


def generate_sub_id():
    timestamp = floor(time() * 1000)
    random_id = randint(0, 999)
    return f'sub-{timestamp}-{random_id:03}'


def z2state(z: str) -> List[List[int]]:
    return [[{"z": -1, "Z": 1, "0": 0}[j] for j in z[i:i + 14]] for i in range(0, 196, 14)]


def state2z(state: List[List[int]]) -> str:
    return "".join(["".join([{-1: "z", 0: "0", 1: "Z"}[j] for j in i]) for i in state])


class Client(websocket.WebSocketApp):
    board_id: int

    last_state: Optional[List[List[int]]] = None

    def __init__(self):
        super().__init__(WS_URL,
                         on_open=self.on_open,
                         on_message=self.on_message,
                         on_error=self.on_error,
                         on_close=self.on_close)

    def subscribe(self):
        response = requests.get(f'{API_URL}/boards/find?game=1&user=10170')
        self.board_id = response.json()['data']['id']
        sub = stomper.subscribe(f"/topic/boards/{self.board_id}/sync", generate_sub_id(), ack='auto')
        self.send(sub)

    def update_board(self, state: List[List[int]]):
        if not self.board_id:
            raise RuntimeError('Please run `subscribe` first.')
        requests.get(f'{API_URL}/boards/{self.board_id}/update', params={
            'state': json.dumps(state)
        })

    @staticmethod
    def on_open(ws: 'Client'):
        ws.send('CONNECT\naccept-version:1.0,1.1,2.0\n\n\x00\n')
        ws.p = Popen(f"java -cp {JAR_PATH} com.jingbh.flamechess.jiuqi.MCTSRunnerWithUser -t 4",
                     shell=True, stdin=PIPE, stdout=PIPE, encoding="utf-8")
        ws.p.stdin.write("-1\n")
        ws.p.stdin.flush()
        ws.p.stdout.readline()

    @staticmethod
    def on_message(ws: 'Client', message):
        decoded_message = stomper.unpack_frame(message)
        if decoded_message['cmd'] == 'CONNECTED':
            ws.subscribe()
        elif decoded_message['cmd'] == 'MESSAGE':
            state: List[List[int]] = json.loads(decoded_message['body'])
            if not ws.last_state or json.dumps(state) != json.dumps(ws.last_state):
                ws.last_state = state
                z = state2z(state)
                print(z)
                ws.p.stdin.write(z+"\n")  # write it
                ws.p.stdin.flush()
                ws.p.stdin.write("0\n")     # stage
                ws.p.stdin.flush()
                respond = ws.p.stdout.readline().strip()
                ws.p.stdout.readline()    # read "Input State:"
                print("respond:", respond)
                ws.last_state = z2state(respond)
                ws.update_board(z2state(respond))
                print("updated")
                # Then use `ws.update_board(new_state)` to update the board.

    @staticmethod
    def on_error(_ws, error):
        print(f'ERROR: {error}')

    @staticmethod
    def on_close(_ws, close_status_code, close_msg):
        print(f'CLOSED: [{close_status_code}] {close_msg}')


if __name__ == '__main__':
    if not API_URL:
        raise ValueError('Please set environment variable `API_URL`.')
    client = Client()
    client.run_forever()
