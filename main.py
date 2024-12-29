from flask import Flask, request, jsonify
import requests
import json
import re
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

def get_youtube_video_id(url):
    # Regular expression to match YouTube video URLs
    regex = r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:[^/]+/.*|(?:v|e(?:mbed)?|watch|.+\?.+)?/|.*[?&]v=)|youtu\.be/)([a-zA-Z0-9_-]{11})'
    
    match = re.search(regex, url)
    if match:
        return match.group(1)
    else:
        return None

def parse_duration(duration):
    if duration.startswith('PT'):
        duration = duration[2:]  # Remove 'PT'
        minutes = 0
        seconds = 0

        if 'H' in duration:
            hours, duration = duration.split('H')
            minutes += int(hours) * 60

        if 'M' in duration:
            minutes_part, duration = duration.split('M')
            minutes += int(minutes_part)

        if 'S' in duration:
            seconds_part = duration.split('S')[0]
            seconds = int(seconds_part) if seconds_part else 0

        return minutes + seconds / 60  # Return total minutes
    return 0

def clean_response(response_text):
    if not response_text:
        return ''

    cleaned_response = response_text.strip()

    if '$~~~$' in cleaned_response:
        cleaned_response = re.sub(r'\$~~~\$.*?\$~~~\$', '', cleaned_response, flags=re.DOTALL)
        cleaned_response = cleaned_response.strip()
        cleaned_response = cleaned_response[7:].strip()

    cleaned_response = re.sub(
        r'Generated by BLACKBOX\.AI.*?https:\/\/api\.blackbox\.ai[\n]*',
        '',
        cleaned_response
    )

    cleaned_response = re.sub(r'\{.*?\}', '', cleaned_response)
    cleaned_response = re.sub(r'\n{3,}', '\n\n', cleaned_response)
    
    return cleaned_response.strip()

@app.route('/process', methods=['GET'])
def process_video():
    try:
        url = request.args.get('url')
        if not url:
            return jsonify({"error": "URL parameter is required"}), 400

        # Get video ID
        video_id = get_youtube_video_id(url)
        if not video_id:
            return jsonify({"error": "Invalid YouTube URL"}), 400

        # First request - Check video duration
        headers_duration = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'accept-language': 'en-US,en;q=0.9,de;q=0.8',
            'origin': 'https://mattw.io',
            'referer': 'https://mattw.io/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }

        params_duration = {
            'key': 'foo',
            'part': 'contentDetails',
            'id': video_id,
        }

        response = requests.get('https://ytapi.apps.mattw.io/v3/videos', params=params_duration, headers=headers_duration)
        duration = response.json()['items'][0]['contentDetails']['duration']
        total_minutes = parse_duration(duration)

        if total_minutes > 30:
            return jsonify({"error": "Video duration exceeds 30 minutes"}), 400

        # Second request - Get author URL
        headers_embed = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9,de;q=0.8',
            'origin': 'https://tubepilot.ai',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }

        response = requests.get('https://noembed.com/embed', params={'url': url}, headers=headers_embed)
        author_url = response.json().get('author_url')

        # Third request - Get transcript and thumbnail
        headers_transcript = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9,de;q=0.8',
            'content-type': 'application/json',
            'origin': 'https://submagic-free-tools.fly.dev',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }

        response = requests.post(
            'https://submagic-free-tools.fly.dev/api/youtube-transcription',
            headers=headers_transcript,
            json={'url': url}
        )
        
        transcript_data = response.json()
        thumbnailUrl = transcript_data['thumbnailUrl']
        transcript = transcript_data['transcripts']['en']

        if not transcript or not thumbnailUrl:
            return jsonify({"error": "Failed to get transcript or thumbnail"}), 400

        # Final request - Generate article
        headers_blackbox = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9,de;q=0.8",
            "content-type": "application/json",
            "origin": "https://www.blackbox.ai",
            "referer": "https://www.blackbox.ai/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }

        json_data = {
            "messages": [
                {
                    "id": "EDDwgrS",
                    "content": (
                        f"The following is the transcript of a YouTube video, "
                        f"{'along with the user profile URL: ' + author_url + '. ' if author_url else ''}"
                        f"Please use this information to craft a well-structured and engaging article.\n\n"
                        f"{transcript}"
                    ),
                    "role": "user"
                }
            ],
            "id": "EDDwgrS",
            "previewToken": None,
            "userId": None,
            "codeModelMode": True,
            "agentMode": {},
            "trendingAgentMode": {},
            "isMicMode": False,
            "userSystemPrompt": None,
            "maxTokens": 1024,
            "playgroundTopP": 0.9,
            "playgroundTemperature": 0.5,
            "isChromeExt": False,
            "githubToken": "",
            "validated": "00f37b34-a166-4efb-bce5-1312d87f2f94",
            "imageGenerationMode": False,
            "webSearchModePrompt": False
        }

        response = requests.post(
            "https://blackbox.ai/api/chat",
            headers=headers_blackbox,
            json=json_data,
            timeout=30
        )
        response.raise_for_status()

        cleaned_article = clean_response(response.text)

        return jsonify({
            "thumbnail_url": thumbnailUrl,
            "article": cleaned_article,
            "author_url": author_url,
            "duration_minutes": total_minutes
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)