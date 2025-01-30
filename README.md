
# Realtime OpenAI Chat Application

A Flask/FastAPI application that integrates with Twilio and OpenAI's real-time API to provide voice-based AI assistance for wildfire relief and disaster response.

## Features

- Real-time voice communication using Twilio
- OpenAI GPT-4 integration for natural language processing
- Call logging system
- Customizable system prompts via prompts.json
- Support for multiple concurrent calls
- Automatic logging directory management

## Prerequisites

- Python 3.10 or higher
- OpenAI API key
- Twilio account and credentials

## Environment Variables

The following environment variables are required:

- `OPENAI_API_KEY`: Your OpenAI API key
- `PORT`: Server port (default: 5000)

## Installation

1. Clone this repository
2. Install dependencies:
```bash
poetry install
```

## Usage

1. Set up your environment variables
2. Start the server:
```bash
python main.py
```

The server will start on the configured port, ready to handle incoming Twilio calls.

## API Endpoints

- `GET /`: Health check endpoint
- `GET/POST /incoming-call`: Handles incoming Twilio calls
- `WebSocket /media-stream`: Handles real-time audio streaming

## Logging

Call logs are stored in the `logs` directory with the format:
```
call_YYYYMMDD_HHMMSS_[StreamSID].log
```

## Project Structure

```
├── logs/           # Call logs directory
├── templates/      # HTML templates
├── main.py        # Main application file
├── prompts.json   # System prompts configuration
└── pyproject.toml # Project dependencies
```

## License

See LICENSE file for details.

## Note

This application is specifically designed for disaster response and wildfire relief assistance. It includes a comprehensive knowledge base of resources, accommodations, and support services.
