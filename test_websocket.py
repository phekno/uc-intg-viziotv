#!/usr/bin/env python3
"""
Test script for connecting to the Vizio TV integration WebSocket server.
"""

import asyncio
import json
import logging
import sys
import websockets

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("test_websocket")

async def connect_and_send(uri, message):
    """
    Connect to a WebSocket server, send a message, and handle the response.
    
    Args:
        uri: The WebSocket URI to connect to
        message: The message to send (as a dictionary)
    """
    try:
        logger.info(f"Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            logger.info("Connected!")
            
            # Receive initial message (likely authentication info)
            logger.info("Waiting for initial message...")
            initial_msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            logger.info(f"Received initial message: {initial_msg}")
            
            try:
                initial_json = json.loads(initial_msg)
                logger.info(f"Parsed initial message: {json.dumps(initial_json, indent=2)}")
                
                # Extract request ID from initial message
                req_id = initial_json.get("req_id", 0)
                
                # Skip sending authentication response, go straight to command
                # Prepare the message with proper format - order matters!
                new_message = {
                    "req_id": str(req_id + 1),  # Use string instead of number
                    "kind": "req",
                    "msg": message.get("type", "ping")  # Use type as msg if present
                }
                
                # Remove type field if it exists to avoid confusion
                if "type" in message and "type" not in new_message:
                    logger.info("Removing 'type' field from message")
                
                # Add any other fields from the original message
                for key, value in message.items():
                    if key not in ["type", "req_id", "kind", "msg"]:
                        new_message[key] = value
                
                # Use the new message instead of the original
                message = new_message
                message_str = json.dumps(message)
                logger.info(f"Sending message: {message_str}")
                await websocket.send(message_str)
                logger.info("Message sent, waiting for response...")
                
                # Wait for response with a timeout
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    logger.info(f"Received response: {response}")
                    
                    # Try to parse the response as JSON
                    try:
                        response_json = json.loads(response)
                        logger.info(f"Parsed JSON response: {json.dumps(response_json, indent=2)}")
                    except json.JSONDecodeError:
                        logger.warning("Response is not valid JSON")
                    
                    # Keep the connection open for more messages
                    logger.info("Waiting for more messages (press Ctrl+C to exit)...")
                    while True:
                        try:
                            response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                            logger.info(f"Received: {response}")
                        except asyncio.TimeoutError:
                            # Send a ping to keep the connection alive
                            ping_msg = {
                                "kind": "req",
                                "req_id": req_id + 2,  # Increment request ID
                                "msg": "ping"
                            }
                            logger.info("Sending ping to keep connection alive...")
                            await websocket.send(json.dumps(ping_msg))
                        except websockets.exceptions.ConnectionClosed as e:
                            logger.error(f"Connection closed: {e}")
                            break
                
                except asyncio.TimeoutError:
                    logger.warning("No response received within timeout period")
                
            except json.JSONDecodeError:
                logger.error("Authentication prompt is not valid JSON")
            
    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"Connection closed: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")

async def main():
    """Main function to run the WebSocket test."""
    # Default values
    uri = "ws://localhost:9090"
    message = {"type": "ping"}
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "ping":
            message = {"type": "ping"}
        elif command == "discover":
            message = {"type": "discover"}
        elif command == "get_available_entities":
            message = {"type": "get_available_entities"}
        elif command == "get_device_state":
            message = {"type": "get_device_state"}
        elif command == "driver_setup":
            message = {"type": "driver_setup"}
        else:
            logger.error(f"Unknown command: {command}")
            return
    
    # If a custom URI is provided
    if len(sys.argv) > 2:
        uri = sys.argv[2]
    
    await connect_and_send(uri, message)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exiting...")