import os
import json
import time
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from upyloadthing import UTApi, UTApiOptions
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Global storage for latest cookies and userKey
latest_auth = {
    'cookies': None,
    'userKey': None,
    'timestamp': None
}

# Initialize UploadThing API
UPLOADTHING_TOKEN = os.getenv('UPLOADTHING_TOKEN', 'eyJhcGlLZXkiOiJza19saXZlXzE5ZThmMDZiOTE5MmQwZTUxNDY5OThjNGFhMTk5OWNhYjc5YjI4ODgxYzVhYzUzNzVjYjNhZWJlYzM4YjFiZjMiLCJhcHBJZCI6InVjMXc4NmR5cTAiLCJyZWdpb25zIjpbInNlYTEiXX0=')
ut_api = UTApi(UTApiOptions(token=UPLOADTHING_TOKEN))

@app.route('/webhook/cookies', methods=['POST'])
@app.route('/api/webhook/cookie-token', methods=['POST', 'GET'])
def receive_cookies():
    """Webhook endpoint to receive cookie and userKey updates"""
    try:
        # Log incoming request
        print(f"\n{'='*50}")
        print(f"📥 Webhook received!")
        print(f"Method: {request.method}")
        print(f"Headers: {dict(request.headers)}")
        print(f"Body: {request.get_data(as_text=True)}")
        print(f"{'='*50}\n")
        
        data = request.json
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Handle both formats: direct and wrapped in 'data'
        # Direct format: {"cookies": {...}, "userKey": "..."}
        # Wrapped format: {"data": {"cookies": {...}, "userKey": "..."}}
        if 'data' in data:
            webhook_data = data.get('data', {})
        else:
            webhook_data = data
        
        new_cookies = webhook_data.get('cookies')
        new_userKey = webhook_data.get('userKey')
        new_timestamp = webhook_data.get('timestamp')
        
        if not new_cookies or not new_userKey:
            print(f"✗ Missing data - cookies: {bool(new_cookies)}, userKey: {bool(new_userKey)}")
            return jsonify({'error': 'Missing cookies or userKey in webhook data'}), 400
        
        # Compare with existing data
        if (latest_auth['cookies'] != new_cookies or 
            latest_auth['userKey'] != new_userKey):
            
            # Update with fresh data
            latest_auth['cookies'] = new_cookies
            latest_auth['userKey'] = new_userKey
            latest_auth['timestamp'] = new_timestamp or datetime.utcnow().isoformat()
            
            print(f"✓ Updated auth data at {latest_auth['timestamp']}")
            return jsonify({
                'status': 'updated',
                'message': 'Authentication data updated successfully',
                'timestamp': latest_auth['timestamp']
            }), 200
        else:
            print("✓ Auth data unchanged, skipping update")
            return jsonify({
                'status': 'unchanged',
                'message': 'Authentication data is already up to date',
                'timestamp': latest_auth['timestamp']
            }), 200
            
    except Exception as e:
        print(f"✗ Error in webhook: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/generate', methods=['POST'])
def generate_image():
    """API endpoint to generate and upload an image"""
    try:
        # Check if we have authentication data
        if not latest_auth['cookies'] or not latest_auth['userKey']:
            return jsonify({
                'error': 'No authentication data available. Please send cookies via webhook first.'
            }), 400
        
        # Get prompt from request
        data = request.json
        prompt = data.get('prompt')
        
        if not prompt:
            return jsonify({'error': 'Prompt is required'}), 400
        
        print(f"\n{'='*50}")
        print(f"Generating image for prompt: '{prompt}'")
        print(f"Using auth from: {latest_auth['timestamp']}")
        print(f"{'='*50}\n")
        
        # Generate image
        image_data = generate_perchance_image(prompt)
        
        if not image_data:
            return jsonify({'error': 'Failed to generate image'}), 500
        
        # Upload to UploadThing
        print("Uploading to UploadThing...")
        upload_result = upload_to_uploadthing(image_data, prompt)
        
        if not upload_result:
            return jsonify({'error': 'Failed to upload image'}), 500
        
        print(f"✓ Image uploaded successfully: {upload_result['url']}")
        
        return jsonify({
            'success': True,
            'prompt': prompt,
            'image_url': upload_result['url'],
            'file_key': upload_result['file_key'],
            'size': upload_result['size'],
            'generated_at': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def generate_perchance_image(prompt):
    """Generate image using Perchance API"""
    try:
        cookies = latest_auth['cookies']
        user_key = latest_auth['userKey']
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://image-generation.perchance.org/embed',
            'Origin': 'https://image-generation.perchance.org',
            'Content-Type': 'application/json'
        }
        
        # Generate image
        generate_url = f"https://image-generation.perchance.org/api/generate?userKey={user_key}&requestId=0.{time.time()}&adAccessCode=&__cacheBust=0.{time.time()}"
        
        payload = {
            'prompt': prompt,
            'negativePrompt': '',
            'seed': -1,
            'resolution': '768x512',
            'guidanceScale': 7,
            'channel': 'ai-text-to-image-generator',
            'subChannel': 'public',
            'userKey': user_key,
            'adAccessCode': '',
            'requestId': f'0.{time.time()}'
        }
        
        # Try up to 3 times if waiting for previous request
        for attempt in range(3):
            response = requests.post(generate_url, json=payload, cookies=cookies, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('status')
                
                if status == 'waiting_for_prev_request_to_finish':
                    print(f"Waiting for previous request (attempt {attempt + 1}/3)...")
                    time.sleep(10)
                    continue
                    
                elif status == 'success':
                    image_id = data.get('imageId')
                    print(f"✓ Image generated with ID: {image_id}")
                    
                    # Download the image
                    time.sleep(2)  # Wait for image to be ready
                    download_url = f"https://image-generation.perchance.org/api/downloadTemporaryImage?imageId={image_id}"
                    image_response = requests.get(download_url, cookies=cookies, headers=headers, timeout=30)
                    
                    if image_response.status_code == 200:
                        return image_response.content
                    else:
                        print(f"✗ Failed to download image")
                        return None
                else:
                    print(f"✗ API error: {data.get('error', 'Unknown error')}")
                    return None
        
        print("✗ Max retries reached")
        return None
        
    except Exception as e:
        print(f"✗ Error generating image: {str(e)}")
        return None


def upload_to_uploadthing(image_data, prompt):
    """Upload image to UploadThing"""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
            temp_file.write(image_data)
            temp_path = temp_file.name
        
        try:
            # Upload file
            with open(temp_path, 'rb') as f:
                result = ut_api.upload_files(f, content_disposition='inline', acl='public-read')
            
            if result and len(result) > 0:
                upload_result = result[0]
                return {
                    'url': upload_result.url,
                    'file_key': upload_result.file_key,
                    'size': upload_result.size,
                    'name': upload_result.name
                }
            return None
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print("✓ Temporary file deleted")
                
    except Exception as e:
        print(f"✗ Error uploading to UploadThing: {str(e)}")
        return None


@app.route('/status', methods=['GET'])
def status():
    """Check API status and auth availability"""
    return jsonify({
        'status': 'online',
        'auth_available': latest_auth['cookies'] is not None,
        'auth_timestamp': latest_auth['timestamp'],
        'uploadthing_configured': bool(UPLOADTHING_TOKEN)
    }), 200


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"\n{'='*50}")
    print(f"🚀 Image Generation API Server")
    print(f"{'='*50}")
    print(f"Port: {port}")
    print(f"UploadThing configured: {bool(UPLOADTHING_TOKEN)}")
    print(f"{'='*50}\n")
    
    app.run(host='0.0.0.0', port=port, debug=False)
