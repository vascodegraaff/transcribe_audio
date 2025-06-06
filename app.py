import os
import json
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
    Microphone
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
if not DEEPGRAM_API_KEY:
    raise RuntimeError("Set the environment variable DEEPGRAM_API_KEY before running.")

logger.info(f"Using Deepgram API key: {DEEPGRAM_API_KEY[:5]}...{DEEPGRAM_API_KEY[-5:]}")

# ─── FASTAPI APP & STATIC MOUNT ───────────────────────────────────────────────
app = FastAPI()

# Mount ./static under /static
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve a simple landing page at GET /
@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

@app.get("/transcribe")
async def get_transcribe():
    return FileResponse("static/transcribe.html")
        
@app.websocket("/ws/transcribe/deepgram")
async def transcribe_deepgram_ws(websocket: WebSocket):
    """
    1. Accept browser WebSocket.
    2. Initialize Deepgram client.
    3. Setup callback for transcriptions.
    4. Forward incoming audio bytes to Deepgram.
    """
    logger.info("New connection to /ws/transcribe/deepgram")
    await websocket.accept()
    logger.info("Browser WebSocket accepted")

    # Create Deepgram client with API key
    try:
        deepgram = DeepgramClient(
            api_key=DEEPGRAM_API_KEY
        )
        logger.info("Deepgram client initialized")
    except Exception as e:
        error_message = f"Failed to initialize Deepgram client: {str(e)}"
        logger.error(error_message)
        await websocket.send_json({"error": error_message})
        await websocket.close()
        return

    # Create a websocket connection to Deepgram
    try:
        dg_connection = deepgram.listen.websocket.v("1")
        logger.info("Deepgram connection created")
    except Exception as e:
        error_message = f"Failed to create Deepgram connection: {str(e)}"
        logger.error(error_message)
        await websocket.send_json({"error": error_message})
        await websocket.close()
        return

    # Create a queue for transcript messages
    transcript_queue = asyncio.Queue()
    
    # Setup callback for transcriptions
    def on_message(client, result, **kwargs):
        try:
            if hasattr(result, 'channel') and hasattr(result.channel, 'alternatives') and len(result.channel.alternatives) > 0:
                transcript = result.channel.alternatives[0].transcript
                is_final = getattr(result, 'is_final', False)
                
                if transcript:
                    logger.debug(f"Transcript: {transcript}, Final: {is_final}")
                    # Add message to queue instead of sending directly
                    try:
                        transcript_queue.put_nowait({
                            "text": transcript,
                            "is_final": is_final
                        })
                    except Exception as qe:
                        logger.error(f"Error adding transcript to queue: {str(qe)}")
        except Exception as e:
            logger.error(f"Error in transcript callback: {str(e)}")

    # Register the callback for transcript events
    dg_connection.on(LiveTranscriptionEvents.Transcript, on_message)

    # Create a queue for error messages
    error_queue = asyncio.Queue()
    
    # Setup error callback
    def on_error(client, error, **kwargs):
        error_message = f"Deepgram error: {str(error)}"
        logger.error(error_message)
        try:
            # Add error to queue instead of sending directly
            error_queue.put_nowait({"error": error_message})
        except Exception as qe:
            logger.error(f"Error adding error to queue: {str(qe)}")

    # Register the callback for error events
    dg_connection.on(LiveTranscriptionEvents.Error, on_error)

    # Configure Deepgram transcription options
    options = LiveOptions(
        model="nova-3",
        language="en",
        smart_format=True,
        encoding="linear16",
        channels=1,
        sample_rate=16000,
        interim_results=True
    )

    # Start the connection
    try:
        # Handle start which returns a boolean, not an awaitable
        start_result = dg_connection.start(options)
        if not start_result:
            error_message = "Failed to start Deepgram connection"
            logger.error(error_message)
            await websocket.send_json({"error": error_message})
            await websocket.close()
            return
        logger.info("Deepgram connection started successfully")
    except Exception as e:
        error_message = f"Error starting Deepgram connection: {str(e)}"
        logger.error(error_message)
        await websocket.send_json({"error": error_message})
        await websocket.close()
        return

    # Start a background task to process the transcript and error queues
    async def process_queues():
        try:
            while True:
                # Check for transcript messages
                try:
                    # Use non-blocking get_nowait with a small sleep
                    # to avoid blocking the event loop
                    transcript_msg = transcript_queue.get_nowait()
                    await websocket.send_json(transcript_msg)
                    transcript_queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                
                # Check for error messages
                try:
                    error_msg = error_queue.get_nowait()
                    await websocket.send_json(error_msg)
                    error_queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                
                # Small sleep to avoid consuming too much CPU
                await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Error in queue processor: {str(e)}")
    
    # Start the queue processor task
    queue_task = asyncio.create_task(process_queues())
    
    # Forward audio from browser to Deepgram
    try:
        chunks_sent = 0
        while True:
            audio_chunk = await websocket.receive_bytes()
            # Handle send which might return a boolean, not an awaitable
            send_result = dg_connection.send(audio_chunk)
            chunks_sent += 1
            if chunks_sent % 50 == 0:  # Log less frequently
                logger.debug(f"Sent {chunks_sent} audio chunks to Deepgram")
    except WebSocketDisconnect:
        logger.info("Browser disconnected")
    except Exception as e:
        logger.error(f"Error in audio forwarding: {str(e)}")
    finally:
        # Cancel queue processing task
        if 'queue_task' in locals() and queue_task and not queue_task.done():
            queue_task.cancel()
            try:
                await queue_task
            except asyncio.CancelledError:
                pass
                
        # Clean up
        try:
            # Finish may be a synchronous function that returns a boolean
            finish_result = dg_connection.finish()
            logger.info(f"Deepgram connection finished: {finish_result}")
        except Exception as e:
            logger.error(f"Error finishing Deepgram connection: {str(e)}")
        
        try:
            await websocket.close()
            logger.info("Browser websocket closed")
        except Exception:
            pass