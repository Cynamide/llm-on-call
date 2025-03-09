from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import FileResponse
import os
import logging
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel
from twilio.twiml.voice_response import VoiceResponse
from twilio.rest import Client
import uvicorn
import sys

# Load environment variables from .env file
load_dotenv()

stored_dob = None

app = FastAPI()
ULTRAVOX_API_URL = os.getenv("ULTRAVOX_API_URL")
# Global dictionary to temporarily store configuration per call
call_configs = {}

async def create_ultravox_call(config: dict, api_key: str):
    """
    Creates an Ultravox call using the provided configuration and API key.
    """
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(ULTRAVOX_API_URL, headers=headers, json=config)
        response.raise_for_status()
        return response.json()

@app.get("/")
async def index():
    """
    Serves the HTML page for user input.
    Ensure that the file 'index.html' is in the same directory as this script.
    """
    return FileResponse("index.html")

@app.post("/start-call")
async def start_call(
    twilioAccountSid: str = Form(...),
    twilioAuthToken: str = Form(...),
    twilioPhoneNumber: str = Form(...),
    ultravoxApiKey: str = Form(...),
    systemPrompt: str = Form(...),
    targetPhoneNumber: str = Form(...),
    name: str = Form(...),
):
    """
    Initiates an outbound call using Twilio.
    Stores the Ultravox configuration (API key and system prompt) associated with the call SID.
    """
    # The voice callback URL should be a publicly accessible endpoint.
    # Update BASE_URL (e.g. using ngrok or your production domain) in your environment.
    base_url = "https://ae0c-2603-6081-24f0-93b0-ec9f-77-3c83-f5d4.ngrok-free.app"
    voice_url = f"{base_url}/voice"
    
    try:
        # Initialize Twilio client with user-provided credentials
        client = Client(twilioAccountSid, twilioAuthToken)
        
        # Initiate the outbound call
        call = client.calls.create(
            to=targetPhoneNumber,
            from_=twilioPhoneNumber,
            url=voice_url  # Twilio will request instructions from this URL when the call is answered
        )
        
        # Save configuration data for this call using the call SID as key
        systemPrompt = "Name of the person you are calling is " + name +"\n" + systemPrompt
        call_configs[call.sid] = {
            "ultravoxApiKey": ultravoxApiKey,
            "systemPrompt": systemPrompt
        }
        
        return FileResponse("call.html")
    except Exception as e:
        logging.error("Error initiating call: %s", e)
        return {"error": str(e)}

@app.post("/voice")
async def voice(request: Request):
    """
    Handles Twilio's webhook when the call is answered.
    Retrieves the stored Ultravox configuration, requests a join URL from Ultravox,
    and returns TwiML instructions to stream the call to the Ultravox AI.
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    
    # Retrieve the stored configuration for this call
    config_data = call_configs.pop(call_sid, None)
    
    if config_data is None:
        twiml = VoiceResponse()
        twiml.say("There was an error connecting your call. Please try again later.")
        return Response(content=twiml.to_xml(), media_type="application/xml")
    
    # Build the Ultravox call configuration using the user-supplied system prompt
    ultravox_call_config = {
        "systemPrompt": config_data["systemPrompt"],
        "model": "fixie-ai/ultravox",
        "voice": "Mark",
        "temperature": 0.3,
        "firstSpeaker": "FIRST_SPEAKER_AGENT",
        "selectedTools":[
        { "toolId": "56294126-5a7d-4948-b67d-3b7e13d55ea7" },
        {"toolId": "c71fc77a-41e0-4c81-b218-0b5fb4508df0" },
        ],
        "medium": {"twilio": {}}
    }
    
    try:
        join_response = await create_ultravox_call(ultravox_call_config, config_data["ultravoxApiKey"])
        join_url = join_response.get("joinUrl", "")
        
        # Build the Twilio VoiceResponse to stream the call to Ultravox
        twiml = VoiceResponse()
        connect = twiml.connect()
        connect.stream(url=join_url, name="ultravox")
        
        return Response(content=twiml.to_xml(), media_type="application/xml")
    except Exception as error:
        logging.error("Error handling voice callback for call %s: %s", call_sid, error)
        twiml = VoiceResponse()
        twiml.say("Sorry, there was an error connecting your call.")
        return Response(content=twiml.to_xml(), media_type="application/xml")

class DobRequest(BaseModel):
    dob: str

@app.post("/dob")
async def receive_dob(request: DobRequest):
    global stored_dob
    stored_dob = request.dob
    return {"status": "DOB received successfully", "dob": stored_dob}

@app.get("/dob")
async def get_dob():
    global stored_dob
    temp = stored_dob
    stored_dob = None
    return {"dob": temp}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
