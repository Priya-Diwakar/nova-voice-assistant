import os
import logging
import json
import asyncio
import re
from datetime import datetime
from pathlib import Path as PathLib
from typing import Type, List

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import aiofiles
import speech_recognition as sr
import websockets

import config
import assemblyai as aai
from assemblyai.streaming.v3 import (
    BeginEvent,
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    StreamingParameters,
    TerminationEvent,
    TurnEvent,
)
import google.generativeai as genai

# -------------------------
# FastAPI App Init
# -------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = FastAPI()

BASE_DIR = PathLib(__file__).resolve().parent
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# -------------------------
# Personas
# -------------------------
personas = {
    "Pirate": lambda msg: f"☠️ Ahoy matey! {msg}",
    "Cowboy": lambda msg: f"🤠 Howdy partner! {msg}",
    "Robot":  lambda msg: f"🤖 Beep boop... {msg}",
    "Friendly": lambda msg: f"🙂 Sure! {msg}",
    "pirate": lambda msg: f"☠️ Ahoy matey! Ye said: {msg}",
    "cowboy": lambda msg: f"🤠 Howdy partner! You said: {msg}",
    "robot":  lambda msg: f"🤖 Beep boop. Processing: {msg}",
    "friendly": lambda msg: f"🙂 Hey friend! You said: {msg}",
}

# -------------------------
# Extra Skill Example
# -------------------------
def fetch_news():
    return "📰 Breaking News: AI agents are becoming smarter every day!"

# -------------------------
# Dynamic API Keys Store
# -------------------------
RUNTIME_KEYS = {
    "murf": None,
    "assemblyai": None,
    "gemini": None,
    "news": None,
    "openweather": None,
}

class APIKeys(BaseModel):
    murf: str | None = None
    assemblyai: str | None = None
    gemini: str | None = None
    news: str | None = None
    openweather: str | None = None

@app.post("/set-keys")
async def set_keys(keys: APIKeys):
    """Save API keys dynamically from frontend."""
    if keys.murf: 
        RUNTIME_KEYS["murf"] = keys.murf
    if keys.assemblyai:
        RUNTIME_KEYS["assemblyai"] = keys.assemblyai
    if keys.gemini:
        RUNTIME_KEYS["gemini"] = keys.gemini
        genai.configure(api_key=keys.gemini)
    if keys.news:
        RUNTIME_KEYS["news"] = keys.news
    if keys.openweather:
        RUNTIME_KEYS["openweather"] = keys.openweather

    logging.info(f"Updated API keys: {list(k for k,v in RUNTIME_KEYS.items() if v)}")
    return {"message": "API keys updated successfully"}

# -------------------------
# Simple Audio Upload Route
# -------------------------
@app.post("/upload-audio/")
async def upload_audio(file: UploadFile = File(...), persona: str = "friendly"):
    audio_path = f"temp_{file.filename}"
    async with aiofiles.open(audio_path, "wb") as out_file:
        content = await file.read()
        await out_file.write(content)

    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data)
        except Exception:
            text = "Sorry, I could not understand."

    os.remove(audio_path)

    response = personas.get(persona, personas["friendly"])(text)
    response += "\n\n✨ Extra Skill: " + fetch_news()

    return {"input_text": text, "persona_reply": response}

# -------------------------
# Gemini Setup (Dynamic)
# -------------------------
gemini_model = None
if config.GEMINI_API_KEY:
    RUNTIME_KEYS["gemini"] = config.GEMINI_API_KEY
    genai.configure(api_key=config.GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# -------------------------
# Gemini + Murf Streaming
# -------------------------
async def get_llm_response_stream(transcript: str, client_websocket: WebSocket, chat_history: List[dict]):
    if not transcript or not transcript.strip():
        return

    gemini_key = RUNTIME_KEYS["gemini"] or config.GEMINI_API_KEY
    if not gemini_key:
        logging.error("Cannot get LLM response because Gemini key is missing.")
        return

    genai.configure(api_key=gemini_key)
    gemini_model = genai.GenerativeModel("gemini-1.5-flash")

    logging.info(f"Sending to Gemini with history: '{transcript}'")
    
    murf_key = RUNTIME_KEYS["murf"] or config.MURF_API_KEY
    if not murf_key:
        logging.error("Murf API key not found.")
        return

    murf_uri = f"wss://api.murf.ai/v1/speech/stream-input?api-key={murf_key}&sample_rate=44100&channel_type=MONO&format=MP3"
    
    try:
        async with websockets.connect(murf_uri) as websocket:
            voice_id = "en-US-natalie"
            logging.info(f"Connected to Murf AI, using voice: {voice_id}")
            
            context_id = f"voice-agent-context-{datetime.now().isoformat()}"
            
            config_msg = {"voice_config": {"voiceId": voice_id, "style": "Conversational"}, "context_id": context_id}
            await websocket.send(json.dumps(config_msg))

            async def receive_and_forward_audio():
                first_audio_chunk_received = False
                while True:
                    try:
                        response_str = await websocket.recv()
                        response = json.loads(response_str)

                        # Handle audio chunk
                        if "audio" in response and response["audio"]:
                            if not first_audio_chunk_received:
                                await client_websocket.send_text(json.dumps({"type": "audio_start"}))
                                first_audio_chunk_received = True

                            base_64_chunk = response["audio"]
                            await client_websocket.send_text(json.dumps({
                                "type": "audio",
                                "data": base_64_chunk
                            }))

                        # Handle final message
                        if response.get("final"):
                            await client_websocket.send_text(json.dumps({"type": "audio_end"}))
                            break

                    except (websockets.ConnectionClosed, asyncio.CancelledError):
                        logging.info("Murf WebSocket closed.")
                        try:
                            await client_websocket.send_text(json.dumps({"type": "audio_end"}))
                        except Exception:
                            pass
                        break

                    except json.JSONDecodeError as e:
                        logging.error(f"Invalid JSON from Murf: {e}")
                        await client_websocket.send_text(json.dumps({"type": "error", "message": "Invalid response from Murf"}))
                        break

                    except Exception as e:
                        logging.error(f"Unexpected error in Murf receiver: {e}", exc_info=True)
                        await client_websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
                        break

            receiver_task = asyncio.create_task(receive_and_forward_audio())

            try:
                prompt = f"""You are Diva, a friendly and conversational AI voice assistant.
                Your owner is Dhruv Maniya, a CS student from Surat.
                User said: "{transcript}"
                Respond naturally and in plain text (no markdown)."""
                
                chat_history.append({"role": "user", "parts": [prompt]})
                chat = gemini_model.start_chat(history=chat_history[:-1])

                def generate_sync(): return chat.send_message(prompt, stream=True)
                loop = asyncio.get_running_loop()
                gemini_response_stream = await loop.run_in_executor(None, generate_sync)

                sentence_buffer = ""
                full_response_text = ""
                for chunk in gemini_response_stream:
                    if chunk.text:
                        full_response_text += chunk.text
                        await client_websocket.send_text(json.dumps({"type": "llm_chunk", "data": chunk.text}))
                        sentence_buffer += chunk.text
                        sentences = re.split(r'(?<=[.?!])\s+', sentence_buffer)
                        if len(sentences) > 1:
                            for sentence in sentences[:-1]:
                                if sentence.strip():
                                    text_msg = {"text": sentence.strip(), "end": False, "context_id": context_id}
                                    await websocket.send(json.dumps(text_msg))
                            sentence_buffer = sentences[-1]

                if sentence_buffer.strip():
                    text_msg = {"text": sentence_buffer.strip(), "end": True, "context_id": context_id}
                    await websocket.send(json.dumps(text_msg))
                
                chat_history.append({"role": "model", "parts": [full_response_text]})
                await asyncio.wait_for(receiver_task, timeout=60.0)
            
            finally:
                if not receiver_task.done():
                    receiver_task.cancel()

    except Exception as e:
        logging.error(f"Error in LLM/TTS streaming: {e}", exc_info=True)

# -------------------------
# Routes
# -------------------------
@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# -------------------------
# WebSocket for AssemblyAI
# -------------------------
async def send_client_message(ws: WebSocket, message: dict):
    try:
        await ws.send_text(json.dumps(message))
    except ConnectionError:
        logging.warning("Client disconnected, could not send message.")

@app.websocket("/ws")
async def websocket_audio_streaming(websocket: WebSocket):
    await websocket.accept()
    logging.info("WebSocket connection accepted.")
    main_loop = asyncio.get_running_loop()
    
    llm_task = None
    last_processed_transcript = ""
    chat_history = []
    
    assembly_key = RUNTIME_KEYS["assemblyai"] or config.ASSEMBLYAI_API_KEY
    if not assembly_key:
        await send_client_message(websocket, {"type": "error", "message": "AssemblyAI API key not configured."})
        await websocket.close(code=1000)
        return

    client = StreamingClient(StreamingClientOptions(api_key=assembly_key))

    def on_turn(self: Type[StreamingClient], event: TurnEvent):
        nonlocal last_processed_transcript, llm_task
        transcript_text = event.transcript.strip()
        if event.end_of_turn and event.turn_is_formatted and transcript_text and transcript_text != last_processed_transcript:
            last_processed_transcript = transcript_text
            if llm_task and not llm_task.done():
                llm_task.cancel()
                asyncio.run_coroutine_threadsafe(send_client_message(websocket, {"type": "audio_interrupt"}), main_loop)
            asyncio.run_coroutine_threadsafe(send_client_message(websocket, {"type": "transcription", "text": transcript_text, "end_of_turn": True}), main_loop)
            llm_task = asyncio.run_coroutine_threadsafe(get_llm_response_stream(transcript_text, websocket, chat_history), main_loop)

    client.on(StreamingEvents.Begin, lambda self, e: logging.info("Transcription session started."))
    client.on(StreamingEvents.Turn, on_turn)
    client.on(StreamingEvents.Termination, lambda self, e: logging.info("Transcription terminated."))
    client.on(StreamingEvents.Error, lambda self, e: logging.error(f"AssemblyAI error: {e}"))

    try:
        client.connect(StreamingParameters(sample_rate=16000, format_turns=True))
        await send_client_message(websocket, {"type": "status", "message": "Connected to transcription service."})
        while True:
            try:
                message = await websocket.receive()
                if "bytes" in message and message["bytes"]:
                    client.stream(message["bytes"])
            except WebSocketDisconnect:
                logging.info("Client WebSocket disconnected.")
                break
    except Exception as e:
        logging.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        if llm_task and not llm_task.done():
            llm_task.cancel()
        client.disconnect()
        if websocket.client_state.name != "DISCONNECTED":
            await websocket.close()

# -------------------------
# Run Server
# -------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
