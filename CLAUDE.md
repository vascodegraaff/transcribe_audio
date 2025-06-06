# CLAUDE.md - Guidelines for AI Assistants

## Build & Run Commands
- Run server: `uvicorn app:app --reload`
- Run with specific host/port: `uvicorn app:app --host 0.0.0.0 --port 8000 --reload`
- Run in production: `uvicorn app:app --workers 4`
- Install dependencies: `pip install fastapi uvicorn deepgram-sdk`
- Set Deepgram API key: `export DEEPGRAM_API_KEY=your_api_key_here`

## Code Style Guidelines
- **Imports**: Standard library first, then third-party, then local modules
- **Formatting**: Use 4-space indentation, 120 character line limit
- **Types**: Use type hints for function parameters and return values
- **Naming**: snake_case for variables/functions, PascalCase for classes
- **Error Handling**: Use try/except blocks with specific exceptions
- **Comments**: Use docstrings for functions/classes, inline comments for complex logic
- **Async**: Use async/await for WebSocket handling and external API calls
- **Constants**: Use UPPERCASE for constants like API URLs and configuration

## Project Structure
- FastAPI application for real-time speech transcription
- Uses Deepgram SDK for cloud-based speech recognition
- Static files served from /static directory
- WebSocket endpoint for real-time audio processing

## Implementation Notes
- The WebSocket handler properly handles async callbacks using queues
- The Deepgram SDK methods (start, send, finish) return boolean values, not awaitables
- Audio is processed in 16kHz PCM format (16-bit linear)
- Error handling is in place for all API operations