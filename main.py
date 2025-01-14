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

# Configuration from Replit Secrets
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5000))

# Create logs directory if it doesn't exist
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)


# Load system prompt from JSON file
def load_system_prompt():
    try:
        with open('prompts.json', 'r') as f:
            prompts = json.load(f)
            return prompts['system_message']['content']
    except Exception as e:
        logging.error(f"Error loading system prompt: {str(e)}")
        return "You are a helpful AI assistant."  # Fallback prompt


def setup_call_logger(stream_sid):
    """Set up a logger for a specific call."""
    # Create a unique log file name with timestamp and stream_sid
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"call_{timestamp}_{stream_sid}.log"

    # Create and configure logger
    logger = logging.getLogger(f"call_{stream_sid}")
    logger.setLevel(logging.INFO)

    # Create file handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(file_handler)

    return logger


VOICE = 'shimmer'
LOG_EVENT_TYPES = [
    'response.content.done', 'rate_limits.updated', 'response.done',
    'input_audio_buffer.committed', 'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started', 'session.created', 'turn.start', 'turn.end'
]

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError(
        'Missing the OpenAI API key. Please add it to Replit Secrets.')


@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    response.say(
        "Hello. Welcome to the Supply Drop Resource Assistance Line. I can help you find Wildfire relief resources in Southern California and Hurricane Recovery Resources in Western North Carolina. How can I help?",
        voice="Polly.Matthew")
    response.pause(length=1)
    response.say("How can I help?", voice="Polly.Matthew")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    logger = None
    stream_sid = None
    current_turn_id = None

    print("Client connected")
    await websocket.accept()

    async with websockets.connect(
            'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }) as openai_ws:
        await send_session_update(openai_ws)

        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid, logger
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)

                    # Initialize logger when we get the stream_sid
                    if data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        logger = setup_call_logger(stream_sid)
                        logger.info(f"Call started - Stream SID: {stream_sid}")
                        logger.info(f"Start event payload: {json.dumps(data)}")

                    if data['event'] == 'media' and openai_ws.open:
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        if logger:
                            logger.info("Received audio data from Twilio")
                            logger.debug(
                                f"Audio payload size: {len(data['media']['payload'])}"
                            )
                        await openai_ws.send(json.dumps(audio_append))

            except WebSocketDisconnect:
                if logger:
                    logger.info("Client disconnected")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, logger, current_turn_id
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)

                    if logger:
                        if response['type'] in LOG_EVENT_TYPES:
                            logger.info(f"OpenAI event: {response['type']}")
                            logger.debug(
                                f"Full event payload: {json.dumps(response)}")

                    # Handle turn detection events
                    if response['type'] == 'turn.start':
                        new_turn_id = response.get('turn', {}).get('id')
                        if current_turn_id and current_turn_id != new_turn_id:
                            # Cancel previous turn's response
                            await openai_ws.send(json.dumps({
                                "type": "response.cancel",
                                "turn_id": current_turn_id
                            }))
                            if logger:
                                logger.info(f"Cancelled response for turn {current_turn_id}")
                        current_turn_id = new_turn_id
                        if logger:
                            logger.info(f"New turn started: {current_turn_id}")

                    if response['type'] == 'turn.end':
                        if logger:
                            logger.info(f"Turn ended: {response.get('turn', {}).get('id')}")

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
                            if logger:
                                logger.info("Sent audio response to Twilio")
                                logger.debug(
                                    f"Audio response size: {len(audio_payload)}"
                                )
                        except Exception as e:
                            if logger:
                                logger.error(
                                    f"Error processing audio data: {str(e)}")
            except Exception as e:
                if logger:
                    logger.error(f"Error in send_to_twilio: {str(e)}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())


async def send_session_update(openai_ws):
    """Send session update to OpenAI WebSocket."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad",
                "mode": "normal",
                "time_units": {
                    "speech_gap_ms": 600,
                    "speech_timeout_ms": 6000
                }
            },
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": load_system_prompt(),
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
