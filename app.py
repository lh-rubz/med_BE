from flask import Flask, request
from flask_restx import Api, Resource, fields
from openai import OpenAI

# NOTE: token is hardcoded as requested by the user. For production, use environment variables.
HF_TOKEN = "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"

app = Flask(__name__)
api = Api(app, version="1.0", title="HuggingFace VLM Test API",
          description="Simple API to test Hugging Face VLM via OpenAI-compatible router",
          doc="/swagger")

ns = api.namespace('api/v1', description='VLM endpoints')

prompt_model = api.model('Prompt', {
    'prompt': fields.String(required=True, description='Text prompt to send to the model'),
    'image_url': fields.String(required=False, description='Optional image URL')
})


def create_client():
    # create OpenAI-compatible client pointing at HF router
    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=HF_TOKEN,
    )
    return client


@ns.route('/chat')
class ChatResource(Resource):
    @ns.expect(prompt_model)
    def post(self):
        """Send a prompt (optionally with image) to the Hugging Face VLM"""
        data = request.json or {}
        prompt = data.get('prompt')
        image_url = data.get('image_url')

        if not prompt:
            return {'error': 'prompt is required'}, 400

        client = create_client()

        # Build message content similar to the example provided
        content = [{
            'type': 'text',
            'text': prompt
        }]
        if image_url:
            content.append({
                'type': 'image_url',
                'image_url': {'url': image_url}
            })

        try:
            completion = client.chat.completions.create(
                model="google/gemma-3-12b-it:featherless-ai",
                messages=[
                    {
                        'role': 'user',
                        'content': content
                    }
                ],
            )

            # Return JSON-serializable values: convert objects to strings
            try:
                message = completion.choices[0].message
            except Exception:
                # fallback if structure differs
                message = getattr(completion, 'choices', completion)

            # Ensure serializable (most SDK objects aren't JSON serializable),
            # so convert to string representations for debugging.
            return {'model_response': str(message), 'raw': str(completion)}
        except Exception as e:
            return {'error': str(e)}, 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
