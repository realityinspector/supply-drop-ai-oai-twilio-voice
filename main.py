from flask import Flask, render_template
import os
import json
import base64
import asyncio
import websockets
import logging
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream

# Configuration from environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5000))

# Ensure logs directory exists
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


def load_system_prompt():
    try:
        print("Loading system prompt from prompts.json")
        with open('prompts.json', 'r') as f:
            prompts = json.load(f)
            system_prompt = prompts['system_message']['content']
            print("System prompt loaded successfully")
            return system_prompt
    except Exception as e:
        print(f"Error loading system prompt: {e}")
        return "You are a helpful AI assistant."


def setup_call_logger(stream_sid):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"call_{timestamp}_{stream_sid}.log"

    logger = logging.getLogger(f"call_{stream_sid}")
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(log_file)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    print(f"Logger set up for stream SID: {stream_sid}")
    return logger


VOICE = 'shimmer'
LOG_EVENT_TYPES = [
    'response.content.done', 'rate_limits.updated', 'response.done',
    'input_audio_buffer.committed', 'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started', 'session.created'
]

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError(
        "Missing the OpenAI API key. Please add it to environment variables.")


@app.get("/", response_class=JSONResponse)
async def index_page():
    print("Index page accessed.")
    return {"message": "Twilio Media Stream Server is running!"}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    print("Incoming call received.")
    response = VoiceResponse()
    response.say(
        "Welcome to the Supply Drop AI help line. This is a demonstration of technology and information may be inaccurate. I can help you find non-emergency response and relief resources for the LA Wildfires and Hurricane Helene Recovery.  NOT FOR EMERGENCIES. CALL 911 if you are experiencing an emergency.",
        voice="Polly.Joanna")
    response.pause(length=1)
    response.say("How can I help?", voice="Polly.Joanna")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    print("Generated TwiML response for the call.")
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    logger = None
    stream_sid = None

    print("Client connected to media-stream endpoint.")
    await websocket.accept()

    async with websockets.connect(
            'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }) as openai_ws:
        print("Connected to OpenAI WebSocket.")
        await send_session_update(openai_ws)

        async def receive_from_twilio():
            nonlocal stream_sid, logger
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    print(f"Received message from Twilio: {data}")

                    if data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        logger = setup_call_logger(stream_sid)
                        logger.info(f"Call started - Stream SID: {stream_sid}")

                    if data['event'] == 'media' and openai_ws.open:
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        if logger:
                            logger.info("Received audio data from Twilio")
                        print("Sending audio data to OpenAI.")
                        await openai_ws.send(json.dumps(audio_append))

            except WebSocketDisconnect:
                print("Twilio WebSocket disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            nonlocal stream_sid, logger
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    print(f"Received message from OpenAI: {response}")

                    if logger and response['type'] in LOG_EVENT_TYPES:
                        logger.info(f"OpenAI event: {response['type']}")

                    if response[
                            'type'] == 'response.audio.delta' and response.get(
                                'delta'):
                        try:
                            audio_payload = base64.b64encode(
                                base64.b64decode(
                                    response['delta'])).decode('utf-8')
                            audio_delta = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {
                                    "payload": audio_payload
                                }
                            }
                            await websocket.send_json(audio_delta)
                            print("Sent audio response to Twilio.")
                        except Exception as e:
                            print(f"Error processing audio delta: {e}")
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())


async def send_session_update(openai_ws):
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad"
            },
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": load_system_prompt(),
            "modalities": ["text", "audio"],
            "temperature": 0.8
        }
    }
    print("Sending session update to OpenAI:", json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))


if __name__ == "__main__":
    print("Starting the FastAPI server...")
    app.run(host="0.0.0.0", port=PORT, debug=True)
